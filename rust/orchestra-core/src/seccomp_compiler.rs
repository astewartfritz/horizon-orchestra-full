//! Seccomp-BPF filter compiler for Orchestra sandbox profiles.
//!
//! Compiles high-level syscall allow/deny lists into BPF bytecode that can
//! be loaded via prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ...).

use std::collections::HashSet;

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

use crate::{OrchestraError, OrchestraResult};

// --- BPF instruction constants (Linux seccomp-BPF) ---

/// BPF instruction opcodes.
const BPF_LD: u16 = 0x00;
const BPF_JMP: u16 = 0x05;
const BPF_RET: u16 = 0x06;
const BPF_W: u16 = 0x00;
const BPF_ABS: u16 = 0x20;
const BPF_JEQ: u16 = 0x10;
const BPF_K: u16 = 0x00;

/// Seccomp return values.
const SECCOMP_RET_KILL_PROCESS: u32 = 0x80000000;
const SECCOMP_RET_KILL_THREAD: u32 = 0x00000000;
const SECCOMP_RET_ERRNO: u32 = 0x00050000;
const SECCOMP_RET_ALLOW: u32 = 0x7FFF0000;
const SECCOMP_RET_LOG: u32 = 0x7FFC0000;

/// Offset of the syscall number in the seccomp_data struct (for x86_64).
const SYSCALL_NR_OFFSET: u32 = 0;
/// Offset of the architecture field in seccomp_data.
const ARCH_OFFSET: u32 = 4;
/// x86_64 audit architecture value.
const AUDIT_ARCH_X86_64: u32 = 0xC000003E;

/// A single BPF instruction (8 bytes).
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct BpfInstruction {
    pub opcode: u16,
    pub jt: u8, // jump if true
    pub jf: u8, // jump if false
    pub k: u32, // constant
}

impl BpfInstruction {
    /// Serialize this instruction to 8 bytes (little-endian).
    pub fn to_bytes(&self) -> [u8; 8] {
        let mut buf = [0u8; 8];
        buf[0..2].copy_from_slice(&self.opcode.to_le_bytes());
        buf[2] = self.jt;
        buf[3] = self.jf;
        buf[4..8].copy_from_slice(&self.k.to_le_bytes());
        buf
    }

    /// Create a BPF_LD | BPF_W | BPF_ABS instruction.
    fn ld_abs(offset: u32) -> Self {
        BpfInstruction {
            opcode: BPF_LD | BPF_W | BPF_ABS,
            jt: 0,
            jf: 0,
            k: offset,
        }
    }

    /// Create a BPF_JMP | BPF_JEQ | BPF_K instruction.
    fn jeq(value: u32, jt: u8, jf: u8) -> Self {
        BpfInstruction {
            opcode: BPF_JMP | BPF_JEQ | BPF_K,
            jt,
            jf,
            k: value,
        }
    }

    /// Create a BPF_RET | BPF_K instruction.
    fn ret(value: u32) -> Self {
        BpfInstruction {
            opcode: BPF_RET | BPF_K,
            jt: 0,
            jf: 0,
            k: value,
        }
    }
}

/// Action to take when a syscall is denied.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DenyAction {
    /// Kill the entire process.
    KillProcess,
    /// Kill only the offending thread.
    KillThread,
    /// Return EPERM (Operation not permitted).
    Errno,
    /// Allow but log the syscall.
    Log,
}

impl DenyAction {
    fn to_seccomp_ret(&self) -> u32 {
        match self {
            DenyAction::KillProcess => SECCOMP_RET_KILL_PROCESS,
            DenyAction::KillThread => SECCOMP_RET_KILL_THREAD,
            DenyAction::Errno => SECCOMP_RET_ERRNO | 1, // EPERM = 1
            DenyAction::Log => SECCOMP_RET_LOG,
        }
    }
}

/// Orchestra seccomp profile specifying allowed syscalls.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SeccompProfile {
    /// Human-readable profile name.
    pub name: String,
    /// List of allowed syscall numbers.
    pub allowed_syscalls: Vec<u32>,
    /// Action to take for denied syscalls.
    pub deny_action: DenyAction,
    /// Whether to validate architecture (x86_64 only).
    pub check_arch: bool,
}

impl Default for SeccompProfile {
    fn default() -> Self {
        SeccompProfile {
            name: "default".to_string(),
            allowed_syscalls: Vec::new(),
            deny_action: DenyAction::Errno,
            check_arch: true,
        }
    }
}

/// Compile a seccomp filter from a list of allowed syscall numbers.
///
/// The generated BPF program:
/// 1. (Optional) Validates the architecture is x86_64.
/// 2. Loads the syscall number.
/// 3. Checks each allowed syscall; if matched, returns ALLOW.
/// 4. If no match, returns the deny action.
pub fn compile_filter(profile: &SeccompProfile) -> OrchestraResult<Vec<u8>> {
    let allowed: HashSet<u32> = profile.allowed_syscalls.iter().copied().collect();
    let allowed_sorted: Vec<u32> = {
        let mut v: Vec<u32> = allowed.into_iter().collect();
        v.sort();
        v
    };

    if allowed_sorted.is_empty() {
        return Err(OrchestraError::Seccomp(
            "at least one syscall must be allowed".to_string(),
        ));
    }

    let mut instructions: Vec<BpfInstruction> = Vec::new();
    let deny_ret = profile.deny_action.to_seccomp_ret();

    // Step 1: Architecture check (optional).
    if profile.check_arch {
        // Load architecture.
        instructions.push(BpfInstruction::ld_abs(ARCH_OFFSET));
        // If arch == x86_64, jump over the kill; else kill.
        instructions.push(BpfInstruction::jeq(AUDIT_ARCH_X86_64, 1, 0));
        instructions.push(BpfInstruction::ret(SECCOMP_RET_KILL_PROCESS));
    }

    // Step 2: Load syscall number.
    instructions.push(BpfInstruction::ld_abs(SYSCALL_NR_OFFSET));

    // Step 3: For each allowed syscall, add a JEQ -> ALLOW.
    let num_syscalls = allowed_sorted.len();
    for (i, &syscall_nr) in allowed_sorted.iter().enumerate() {
        let remaining = num_syscalls - i - 1;
        // jt = jump to ALLOW (which is at: remaining checks + 1 deny instruction)
        let jt = (remaining + 1) as u8;
        // jf = next instruction (0 = fall through)
        let jf = 0;
        instructions.push(BpfInstruction::jeq(syscall_nr, jt, jf));
    }

    // Step 4: Default deny.
    instructions.push(BpfInstruction::ret(deny_ret));

    // Step 5: Allow.
    instructions.push(BpfInstruction::ret(SECCOMP_RET_ALLOW));

    // Serialize all instructions to bytes.
    let mut bytecode = Vec::with_capacity(instructions.len() * 8);
    for inst in &instructions {
        bytecode.extend_from_slice(&inst.to_bytes());
    }

    Ok(bytecode)
}

/// Load a compiled seccomp-BPF filter into the current process.
///
/// This calls prctl(PR_SET_NO_NEW_PRIVS) and then prctl(PR_SET_SECCOMP).
/// WARNING: This is irreversible for the current thread/process.
#[cfg(target_os = "linux")]
pub fn load_filter(bytecode: &[u8]) -> OrchestraResult<()> {
    use std::mem;

    if bytecode.len() % 8 != 0 {
        return Err(OrchestraError::Seccomp(
            "bytecode length must be a multiple of 8".to_string(),
        ));
    }

    let num_instructions = bytecode.len() / 8;

    // sock_fprog structure for seccomp.
    #[repr(C)]
    struct SockFprog {
        len: u16,
        filter: *const u8,
    }

    let prog = SockFprog {
        len: num_instructions as u16,
        filter: bytecode.as_ptr(),
    };

    // PR_SET_NO_NEW_PRIVS = 38
    let ret = unsafe { libc::prctl(38, 1, 0, 0, 0) };
    if ret != 0 {
        return Err(OrchestraError::Seccomp(
            "prctl(PR_SET_NO_NEW_PRIVS) failed".to_string(),
        ));
    }

    // PR_SET_SECCOMP = 22, SECCOMP_MODE_FILTER = 2
    let ret = unsafe { libc::prctl(22, 2, &prog as *const SockFprog as usize, 0, 0) };
    if ret != 0 {
        return Err(OrchestraError::Seccomp(
            "prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER) failed".to_string(),
        ));
    }

    Ok(())
}

/// Stub for non-Linux platforms.
#[cfg(not(target_os = "linux"))]
pub fn load_filter(_bytecode: &[u8]) -> OrchestraResult<()> {
    Err(OrchestraError::Seccomp(
        "seccomp is only supported on Linux".to_string(),
    ))
}

/// Pre-built Orchestra sandbox profiles.
pub fn default_sandbox_profile() -> SeccompProfile {
    SeccompProfile {
        name: "orchestra-sandbox".to_string(),
        allowed_syscalls: vec![
            0,   // read
            1,   // write
            2,   // open
            3,   // close
            5,   // fstat
            8,   // lseek
            9,   // mmap
            10,  // mprotect
            11,  // munmap
            12,  // brk
            13,  // rt_sigaction
            14,  // rt_sigprocmask
            21,  // access
            25,  // mremap
            28,  // madvise
            35,  // nanosleep
            39,  // getpid
            56,  // clone
            57,  // fork
            59,  // execve
            60,  // exit
            63,  // uname
            72,  // fcntl
            79,  // getcwd
            96,  // gettimeofday
            102, // getuid
            104, // getgid
            107, // geteuid
            108, // getegid
            110, // getppid
            158, // arch_prctl
            186, // gettid
            202, // futex
            218, // set_tid_address
            228, // clock_gettime
            231, // exit_group
            257, // openat
            262, // newfstatat
            302, // prlimit64
            318, // getrandom
            334, // rseq
        ],
        deny_action: DenyAction::Errno,
        check_arch: true,
    }
}

/// Restrictive profile for untrusted code execution.
pub fn restrictive_profile() -> SeccompProfile {
    SeccompProfile {
        name: "orchestra-restrictive".to_string(),
        allowed_syscalls: vec![
            0,   // read
            1,   // write
            3,   // close
            5,   // fstat
            9,   // mmap
            10,  // mprotect
            11,  // munmap
            12,  // brk
            60,  // exit
            231, // exit_group
            228, // clock_gettime
            318, // getrandom
        ],
        deny_action: DenyAction::KillProcess,
        check_arch: true,
    }
}

// --- PyO3 Python bindings ---

#[pyclass(name = "SeccompCompiler")]
pub struct PySeccompCompiler;

#[pymethods]
impl PySeccompCompiler {
    #[new]
    fn new() -> Self {
        PySeccompCompiler
    }

    /// Compile a seccomp filter from a list of allowed syscall numbers.
    /// Returns the BPF bytecode as bytes.
    #[staticmethod]
    #[pyo3(signature = (allowed_syscalls, deny_action="errno", check_arch=true))]
    fn compile(
        allowed_syscalls: Vec<u32>,
        deny_action: &str,
        check_arch: bool,
    ) -> PyResult<Vec<u8>> {
        let action = match deny_action {
            "kill_process" | "kill" => DenyAction::KillProcess,
            "kill_thread" => DenyAction::KillThread,
            "errno" => DenyAction::Errno,
            "log" => DenyAction::Log,
            _ => {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "deny_action must be 'kill_process', 'kill_thread', 'errno', or 'log'",
                ))
            }
        };

        let profile = SeccompProfile {
            name: "custom".to_string(),
            allowed_syscalls,
            deny_action: action,
            check_arch,
        };

        Ok(compile_filter(&profile)?)
    }

    /// Get the default Orchestra sandbox profile's allowed syscalls.
    #[staticmethod]
    fn default_profile_syscalls() -> Vec<u32> {
        default_sandbox_profile().allowed_syscalls
    }

    /// Get the restrictive profile's allowed syscalls.
    #[staticmethod]
    fn restrictive_profile_syscalls() -> Vec<u32> {
        restrictive_profile().allowed_syscalls
    }

    /// Compile the default sandbox profile to BPF bytecode.
    #[staticmethod]
    fn compile_default_profile() -> PyResult<Vec<u8>> {
        Ok(compile_filter(&default_sandbox_profile())?)
    }

    /// Compile the restrictive profile to BPF bytecode.
    #[staticmethod]
    fn compile_restrictive_profile() -> PyResult<Vec<u8>> {
        Ok(compile_filter(&restrictive_profile())?)
    }
}

/// Register seccomp compiler types in the Python module.
pub fn register_python_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySeccompCompiler>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compile_filter_basic() {
        let profile = SeccompProfile {
            name: "test".to_string(),
            allowed_syscalls: vec![0, 1, 60],
            deny_action: DenyAction::Errno,
            check_arch: true,
        };
        let bytecode = compile_filter(&profile).unwrap();
        // 3 arch check instructions + 1 load + 3 JEQ + 1 deny + 1 allow = 9 instructions * 8 bytes
        assert_eq!(bytecode.len(), 9 * 8);
    }

    #[test]
    fn test_compile_filter_no_arch_check() {
        let profile = SeccompProfile {
            name: "test".to_string(),
            allowed_syscalls: vec![0, 1],
            deny_action: DenyAction::KillProcess,
            check_arch: false,
        };
        let bytecode = compile_filter(&profile).unwrap();
        // 1 load + 2 JEQ + 1 deny + 1 allow = 5 instructions * 8 bytes
        assert_eq!(bytecode.len(), 5 * 8);
    }

    #[test]
    fn test_compile_filter_empty_fails() {
        let profile = SeccompProfile {
            name: "empty".to_string(),
            allowed_syscalls: vec![],
            deny_action: DenyAction::Errno,
            check_arch: false,
        };
        assert!(compile_filter(&profile).is_err());
    }

    #[test]
    fn test_bpf_instruction_bytes() {
        let inst = BpfInstruction::ret(SECCOMP_RET_ALLOW);
        let bytes = inst.to_bytes();
        assert_eq!(bytes.len(), 8);
        // opcode = BPF_RET | BPF_K = 0x06
        assert_eq!(u16::from_le_bytes([bytes[0], bytes[1]]), 0x06);
    }

    #[test]
    fn test_default_profile_compiles() {
        let bytecode = compile_filter(&default_sandbox_profile()).unwrap();
        assert!(!bytecode.is_empty());
    }
}
