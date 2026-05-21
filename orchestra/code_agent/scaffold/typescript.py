from __future__ import annotations

from pathlib import Path

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec

# ── Library variant ──────────────────────────────────────────────

LIB_PKG = """{{
  "name": "{name}",
  "version": "0.1.0",
  "description": "{description}",
  "type": "module",
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "exports": {{
    ".": {{
      "import": "./dist/index.js",
      "types": "./dist/index.d.ts"
    }}
  }},
  "scripts": {{
    "build": "tsup src/index.ts --dts --format esm,cjs",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src/ tests/",
    "typecheck": "tsc --noEmit",
    "prepublishOnly": "npm run build"
  }},
  "devDependencies": {{
    "typescript": "^5.5",
    "tsup": "^8.0",
    "vitest": "^2.0",
    "eslint": "^9.0",
    "@eslint/js": "^9.0",
    "prettier": "^3.0",
    "typescript-eslint": "^8.0"
  }}
}}
"""

LIB_TSCONFIG = """{{
  "compilerOptions": {{
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "outDir": "dist",
    "declaration": true,
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "isolatedModules": true
  }},
  "include": ["src"],
  "exclude": ["node_modules", "dist"]
}}
"""

LIB_INDEX = """export function greet(name: string): string {{
  return `Hello, ${{name}}!`;
}}

export const VERSION = "0.1.0";
"""

LIB_TEST = """import {{ describe, it, expect }} from 'vitest';
import {{ greet }} from '../src/index.js';

describe('greet', () => {{
  it('returns greeting', () => {{
    expect(greet('World')).toBe('Hello, World!');
  }});
}});
"""

# ── CLI variant ─────────────────────────────────────────────────

CLI_PKG = """{{
  "name": "{name}",
  "version": "0.1.0",
  "description": "{description}",
  "type": "module",
  "bin": {{
    "{name}": "./dist/cli.js"
  }},
  "scripts": {{
    "build": "tsup src/cli.ts --format esm --clean",
    "test": "vitest run",
    "lint": "eslint src/ tests/",
    "typecheck": "tsc --noEmit"
  }},
  "devDependencies": {{
    "typescript": "^5.5",
    "tsup": "^8.0",
    "vitest": "^2.0",
    "eslint": "^9.0",
    "@eslint/js": "^9.0",
    "prettier": "^3.0",
    "typescript-eslint": "^8.0",
    "@types/node": "^22.0"
  }},
  "dependencies": {{
    "commander": "^12.0"
  }}
}}
"""

CLI_SRC = """#!/usr/bin/env node
import {{ Command }} from 'commander';

const program = new Command();

program
  .name('{name}')
  .description('{description}')
  .version('0.1.0')
  .argument('[input]', 'input to process')
  .option('-v, --verbose', 'verbose output')
  .action((input: string | undefined, opts: {{ verbose?: boolean }}) => {{
    if (opts.verbose) console.log('verbose mode');
    console.log(input ? `Processing: ${{input}}` : 'Hello from {name}');
  }});

program.parse();
"""

# ── Next.js variant ──────────────────────────────────────────────

NEXT_PKG = """{{
  "name": "{name}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint src/",
    "typecheck": "tsc --noEmit"
  }},
  "dependencies": {{
    "next": "^14.2",
    "react": "^18.3",
    "react-dom": "^18.3"
  }},
  "devDependencies": {{
    "typescript": "^5.5",
    "@types/node": "^22.0",
    "@types/react": "^18.3",
    "@types/react-dom": "^18.3",
    "eslint": "^9.0",
    "@eslint/js": "^9.0",
    "typescript-eslint": "^8.0",
    "tailwindcss": "^3.4",
    "postcss": "^8.4",
    "autoprefixer": "^10.4"
  }}
}}
"""

NEXT_TSCONFIG = """{{
  "compilerOptions": {{
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{{ "name": "next" }}],
    "paths": {{ "@/*": ["./src/*"] }}
  }},
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}}
"""

NEXT_LAYOUT = """import type {{ Metadata }} from 'next';
import './globals.css';

export const metadata: Metadata = {{
  title: '{name}',
  description: '{description}',
}};

export default function RootLayout({{
  children,
}}: {{
  children: React.ReactNode;
}}) {{
  return (
    <html lang="en">
      <body>{{children}}</body>
    </html>
  );
}}
"""

NEXT_PAGE = """export default function Home() {{
  return (
    <main>
      <h1>{name}</h1>
      <p>{description}</p>
    </main>
  );
}}
"""

NEXT_GLOBALS_CSS = """@tailwind base;
@tailwind components;
@tailwind utilities;

body {{
  font-family: system-ui, sans-serif;
  padding: 2rem;
}}
"""

NEXT_TAILWIND = """/** @type {{import('tailwindcss').Config}} */
module.exports = {{
  content: ['./src/**/*.{{js,ts,jsx,tsx,mdx}}'],
  theme: {{ extend: {{}} }},
  plugins: [],
}};
"""

NEXT_POSTCSS = """module.exports = {{
  plugins: {{
    tailwindcss: {{}},
    autoprefixer: {{}},
  }},
}};
"""

# ── Shared files ────────────────────────────────────────────────

ESLINT_CONFIG = """import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {{
    rules: {{
      '@typescript-eslint/no-unused-vars': ['warn', {{ argsIgnorePattern: '^_' }}],
    }},
  }},
);
"""

PRETTIERRC = """{{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2
}}
"""

GITIGNORE_TS = """node_modules/
dist/
.next/
*.tsbuildinfo
.env
.env.local
"""

CI_TS = """name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: 20
        cache: 'npm'
    - run: npm ci
    - run: npm run typecheck
    - run: npm run lint
    - run: npm test
    - run: npm run build
"""

README_TS = '''# {name}

{description}

## Quick Start

```bash
npm install
npm run build
npm test
npm run lint
```

## License

MIT
'''


TYPESCRIPT_TEMPLATES: dict[str, dict[str, str]] = {
    "typescript-lib": {
        "package.json": LIB_PKG,
        "tsconfig.json": LIB_TSCONFIG,
        "src/index.ts": LIB_INDEX,
        "tests/index.test.ts": LIB_TEST,
        "eslint.config.js": ESLINT_CONFIG,
        ".prettierrc": PRETTIERRC,
        ".github/workflows/ci.yml": CI_TS,
        ".gitignore": GITIGNORE_TS,
        "README.md": README_TS,
    },
    "typescript-cli": {
        "package.json": CLI_PKG,
        "tsconfig.json": LIB_TSCONFIG,
        "src/cli.ts": CLI_SRC,
        "tests/cli.test.ts": LIB_TEST,
        "eslint.config.js": ESLINT_CONFIG,
        ".prettierrc": PRETTIERRC,
        ".github/workflows/ci.yml": CI_TS,
        ".gitignore": GITIGNORE_TS,
        "README.md": README_TS,
    },
    "typescript-nextjs": {
        "package.json": NEXT_PKG,
        "tsconfig.json": NEXT_TSCONFIG,
        "src/app/layout.tsx": NEXT_LAYOUT,
        "src/app/page.tsx": NEXT_PAGE,
        "src/app/globals.css": NEXT_GLOBALS_CSS,
        "tailwind.config.js": NEXT_TAILWIND,
        "postcss.config.js": NEXT_POSTCSS,
        "eslint.config.js": ESLINT_CONFIG,
        ".prettierrc": PRETTIERRC,
        ".gitignore": GITIGNORE_TS,
        "README.md": README_TS,
    },
}


class TypeScriptScaffold(Tool):
    spec = ToolSpec(
        name="scaffold_ts",
        description="Generate a TypeScript project. Variants: typescript-lib (tsup+vitest), typescript-cli (commander+vitest), typescript-nextjs (Next.js 14+Tailwind). All include ESLint, Prettier, CI.",
        parameters={
            "variant": {"type": "string", "description": "Project variant: typescript-lib, typescript-cli, typescript-nextjs", "enum": ["typescript-lib", "typescript-cli", "typescript-nextjs"]},
            "name": {"type": "string", "description": "Project name"},
            "description": {"type": "string", "description": "Short description", "default": ""},
            "output_dir": {"type": "string", "description": "Output directory"},
        },
    )

    async def __call__(self, variant: str = "typescript-lib", name: str = "", description: str = "", output_dir: str | None = None) -> ToolResult:
        if variant not in TYPESCRIPT_TEMPLATES:
            return ToolResult(error=f"Unknown variant: {variant}. Available: {', '.join(TYPESCRIPT_TEMPLATES)}")
        out = Path(output_dir or name).resolve()
        out.mkdir(parents=True, exist_ok=True)
        created = []
        for relpath, content in TYPESCRIPT_TEMPLATES[variant].items():
            fpath = out / relpath
            fpath.parent.mkdir(parents=True, exist_ok=True)
            formatted = content.format(name=name, description=description or f"A TypeScript project")
            fpath.write_text(formatted, "utf-8")
            created.append(str(fpath.relative_to(out.parent)))
        summary = "\n".join(f"  + {p}" for p in created)
        return ToolResult(output=f"Scaffolded {variant} '{name}' at {out}\n{summary}")
