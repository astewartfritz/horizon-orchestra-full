//! Fast JSON streaming parser with field extraction and schema validation.
//!
//! Designed for high-throughput processing of large JSON payloads and
//! NDJSON (newline-delimited JSON) streams.

use std::io::{BufRead, BufReader, Read};

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{OrchestraError, OrchestraResult};

/// Error encountered during schema validation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationError {
    /// JSON pointer path to the error location (e.g., "/users/0/name").
    pub path: String,
    /// Human-readable error message.
    pub message: String,
    /// The expected type or constraint.
    pub expected: String,
    /// The actual value found (stringified).
    pub actual: String,
}

/// A simple JSON schema definition for validation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JsonSchema {
    /// Expected type: "object", "array", "string", "number", "boolean", "null".
    #[serde(rename = "type")]
    pub schema_type: String,
    /// For objects: required field names.
    #[serde(default)]
    pub required: Vec<String>,
    /// For objects: property schemas keyed by field name.
    #[serde(default)]
    pub properties: std::collections::HashMap<String, JsonSchema>,
    /// For arrays: schema for array items.
    #[serde(default)]
    pub items: Option<Box<JsonSchema>>,
    /// Minimum value (for numbers) or minimum length (for strings/arrays).
    #[serde(default)]
    pub minimum: Option<f64>,
    /// Maximum value (for numbers) or maximum length (for strings/arrays).
    #[serde(default)]
    pub maximum: Option<f64>,
    /// Regex pattern for string validation.
    #[serde(default)]
    pub pattern: Option<String>,
    /// Enumeration of allowed values.
    #[serde(default)]
    pub enum_values: Option<Vec<Value>>,
}

/// Iterator over JSON values parsed from a streaming reader (NDJSON or JSON array).
pub struct JsonStreamIterator<R: Read> {
    reader: BufReader<R>,
    buffer: String,
    done: bool,
}

impl<R: Read> JsonStreamIterator<R> {
    /// Create a new streaming JSON parser from a reader.
    pub fn new(reader: R) -> Self {
        JsonStreamIterator {
            reader: BufReader::new(reader),
            buffer: String::new(),
            done: false,
        }
    }
}

impl<R: Read> Iterator for JsonStreamIterator<R> {
    type Item = OrchestraResult<Value>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.done {
            return None;
        }

        loop {
            self.buffer.clear();
            match self.reader.read_line(&mut self.buffer) {
                Ok(0) => {
                    self.done = true;
                    return None;
                }
                Ok(_) => {
                    let line = self.buffer.trim();
                    if line.is_empty() {
                        continue; // Skip blank lines.
                    }

                    match serde_json::from_str::<Value>(line) {
                        Ok(value) => return Some(Ok(value)),
                        Err(e) => {
                            return Some(Err(OrchestraError::JsonParser(format!(
                                "parse error: {}",
                                e
                            ))));
                        }
                    }
                }
                Err(e) => {
                    self.done = true;
                    return Some(Err(OrchestraError::Io(e)));
                }
            }
        }
    }
}

/// Parse a streaming NDJSON reader into an iterator of Values.
pub fn parse_json_stream<R: Read>(reader: R) -> JsonStreamIterator<R> {
    JsonStreamIterator::new(reader)
}

/// Extract a field from a JSON value using a dot-separated path.
///
/// Path examples: "name", "user.email", "items.0.title"
pub fn extract_field(json: &Value, path: &str) -> Option<Value> {
    let parts: Vec<&str> = path.split('.').collect();
    let mut current = json;

    for part in parts {
        match current {
            Value::Object(map) => {
                current = map.get(part)?;
            }
            Value::Array(arr) => {
                let index: usize = part.parse().ok()?;
                current = arr.get(index)?;
            }
            _ => return None,
        }
    }

    Some(current.clone())
}

/// Validate a JSON value against a schema, returning all validation errors.
pub fn validate_schema(json: &Value, schema: &JsonSchema) -> Vec<ValidationError> {
    let mut errors = Vec::new();
    validate_recursive(json, schema, "", &mut errors);
    errors
}

/// Recursive schema validation.
fn validate_recursive(
    value: &Value,
    schema: &JsonSchema,
    path: &str,
    errors: &mut Vec<ValidationError>,
) {
    // Type check.
    let actual_type = value_type_name(value);
    if !type_matches(value, &schema.schema_type) {
        errors.push(ValidationError {
            path: path.to_string(),
            message: format!("expected type '{}', got '{}'", schema.schema_type, actual_type),
            expected: schema.schema_type.clone(),
            actual: actual_type.to_string(),
        });
        return; // Don't validate further if type is wrong.
    }

    // Enum check.
    if let Some(ref enum_values) = schema.enum_values {
        if !enum_values.contains(value) {
            errors.push(ValidationError {
                path: path.to_string(),
                message: format!("value not in allowed enum values"),
                expected: format!("{:?}", enum_values),
                actual: value.to_string(),
            });
        }
    }

    match value {
        Value::Object(map) => {
            // Check required fields.
            for required_field in &schema.required {
                if !map.contains_key(required_field) {
                    errors.push(ValidationError {
                        path: format!("{}/{}", path, required_field),
                        message: format!("required field '{}' is missing", required_field),
                        expected: "present".to_string(),
                        actual: "missing".to_string(),
                    });
                }
            }

            // Validate properties.
            for (key, prop_schema) in &schema.properties {
                if let Some(prop_value) = map.get(key) {
                    let prop_path = if path.is_empty() {
                        format!("/{}", key)
                    } else {
                        format!("{}/{}", path, key)
                    };
                    validate_recursive(prop_value, prop_schema, &prop_path, errors);
                }
            }
        }
        Value::Array(arr) => {
            // Check length constraints.
            if let Some(min) = schema.minimum {
                if (arr.len() as f64) < min {
                    errors.push(ValidationError {
                        path: path.to_string(),
                        message: format!("array length {} below minimum {}", arr.len(), min),
                        expected: format!(">= {}", min),
                        actual: arr.len().to_string(),
                    });
                }
            }
            if let Some(max) = schema.maximum {
                if (arr.len() as f64) > max {
                    errors.push(ValidationError {
                        path: path.to_string(),
                        message: format!("array length {} above maximum {}", arr.len(), max),
                        expected: format!("<= {}", max),
                        actual: arr.len().to_string(),
                    });
                }
            }

            // Validate items.
            if let Some(ref item_schema) = schema.items {
                for (i, item) in arr.iter().enumerate() {
                    let item_path = format!("{}/{}", path, i);
                    validate_recursive(item, item_schema, &item_path, errors);
                }
            }
        }
        Value::Number(n) => {
            let num = n.as_f64().unwrap_or(0.0);
            if let Some(min) = schema.minimum {
                if num < min {
                    errors.push(ValidationError {
                        path: path.to_string(),
                        message: format!("value {} below minimum {}", num, min),
                        expected: format!(">= {}", min),
                        actual: num.to_string(),
                    });
                }
            }
            if let Some(max) = schema.maximum {
                if num > max {
                    errors.push(ValidationError {
                        path: path.to_string(),
                        message: format!("value {} above maximum {}", num, max),
                        expected: format!("<= {}", max),
                        actual: num.to_string(),
                    });
                }
            }
        }
        Value::String(s) => {
            if let Some(min) = schema.minimum {
                if (s.len() as f64) < min {
                    errors.push(ValidationError {
                        path: path.to_string(),
                        message: format!("string length {} below minimum {}", s.len(), min),
                        expected: format!(">= {}", min),
                        actual: s.len().to_string(),
                    });
                }
            }
            if let Some(max) = schema.maximum {
                if (s.len() as f64) > max {
                    errors.push(ValidationError {
                        path: path.to_string(),
                        message: format!("string length {} above maximum {}", s.len(), max),
                        expected: format!("<= {}", max),
                        actual: s.len().to_string(),
                    });
                }
            }
        }
        _ => {}
    }
}

/// Return the JSON type name for a value.
fn value_type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

/// Check if a value matches the expected type string.
fn type_matches(value: &Value, expected: &str) -> bool {
    match expected {
        "object" => value.is_object(),
        "array" => value.is_array(),
        "string" => value.is_string(),
        "number" | "integer" => value.is_number(),
        "boolean" => value.is_boolean(),
        "null" => value.is_null(),
        "any" => true,
        _ => false,
    }
}

// --- PyO3 Python bindings ---

/// Python-exposed JSON parser utilities.
#[pyclass(name = "JsonParser")]
pub struct PyJsonParser;

#[pymethods]
impl PyJsonParser {
    #[new]
    fn new() -> Self {
        PyJsonParser
    }

    /// Extract a field from a JSON string using a dot-separated path.
    #[staticmethod]
    fn extract(json_str: &str, path: &str) -> PyResult<Option<String>> {
        let value: Value = serde_json::from_str(json_str)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("invalid JSON: {}", e)))?;

        Ok(extract_field(&value, path).map(|v| v.to_string()))
    }

    /// Validate a JSON string against a schema string, returning errors.
    #[staticmethod]
    fn validate(json_str: &str, schema_str: &str) -> PyResult<Vec<(String, String)>> {
        let value: Value = serde_json::from_str(json_str)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("invalid JSON: {}", e)))?;
        let schema: JsonSchema = serde_json::from_str(schema_str)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("invalid schema: {}", e)))?;

        let errors = validate_schema(&value, &schema);
        Ok(errors.into_iter().map(|e| (e.path, e.message)).collect())
    }

    /// Parse NDJSON string into a list of JSON strings.
    #[staticmethod]
    fn parse_ndjson(data: &str) -> PyResult<Vec<String>> {
        let cursor = std::io::Cursor::new(data.as_bytes());
        let iter = parse_json_stream(cursor);
        let mut results = Vec::new();

        for item in iter {
            match item {
                Ok(value) => results.push(value.to_string()),
                Err(e) => return Err(pyo3::exceptions::PyValueError::new_err(e.to_string())),
            }
        }

        Ok(results)
    }
}

/// Register JSON parser types in the Python module.
pub fn register_python_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyJsonParser>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_field_simple() {
        let json: Value = serde_json::from_str(r#"{"name": "Alice", "age": 30}"#).unwrap();
        assert_eq!(extract_field(&json, "name"), Some(Value::String("Alice".to_string())));
        assert_eq!(extract_field(&json, "age"), Some(serde_json::json!(30)));
        assert_eq!(extract_field(&json, "missing"), None);
    }

    #[test]
    fn test_extract_field_nested() {
        let json: Value = serde_json::from_str(r#"{"user": {"email": "a@b.com"}}"#).unwrap();
        assert_eq!(
            extract_field(&json, "user.email"),
            Some(Value::String("a@b.com".to_string()))
        );
    }

    #[test]
    fn test_extract_field_array() {
        let json: Value = serde_json::from_str(r#"{"items": ["a", "b", "c"]}"#).unwrap();
        assert_eq!(
            extract_field(&json, "items.1"),
            Some(Value::String("b".to_string()))
        );
    }

    #[test]
    fn test_validate_schema_valid() {
        let json: Value = serde_json::from_str(r#"{"name": "Alice", "age": 30}"#).unwrap();
        let schema = JsonSchema {
            schema_type: "object".to_string(),
            required: vec!["name".to_string()],
            properties: std::collections::HashMap::new(),
            items: None,
            minimum: None,
            maximum: None,
            pattern: None,
            enum_values: None,
        };
        let errors = validate_schema(&json, &schema);
        assert!(errors.is_empty());
    }

    #[test]
    fn test_validate_schema_missing_required() {
        let json: Value = serde_json::from_str(r#"{"age": 30}"#).unwrap();
        let schema = JsonSchema {
            schema_type: "object".to_string(),
            required: vec!["name".to_string()],
            properties: std::collections::HashMap::new(),
            items: None,
            minimum: None,
            maximum: None,
            pattern: None,
            enum_values: None,
        };
        let errors = validate_schema(&json, &schema);
        assert_eq!(errors.len(), 1);
        assert!(errors[0].message.contains("missing"));
    }
}
