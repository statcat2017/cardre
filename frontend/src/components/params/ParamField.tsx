import React from "react";
import type { SafeDefinition } from "./paramsTypes";

interface Props {
  param: SafeDefinition;
  value: unknown;
  error?: string;
  disabled: boolean;
  onChange: (val: unknown) => void;
}

export function ParamField({ param, value, error, disabled, onChange }: Props) {
  const inputStyle: React.CSSProperties = {
    display: "block",
    width: "100%",
    padding: "4px 8px",
    border: error ? "1px solid #dc2626" : "1px solid #d1d5db",
    borderRadius: 4,
    fontSize: 12,
    boxSizing: "border-box",
    backgroundColor: disabled ? "#f1f5f9" : "#fff",
  };

  const renderControl = () => {
    switch (param.kind) {
      case "string":
        return (
          <input
            type="text"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            style={inputStyle}
          />
        );

      case "integer":
      case "float":
        return (
          <input
            type="number"
            step={param.kind === "float" ? "any" : undefined}
            value={value as number | ""}
            disabled={disabled}
            min={param.constraint?.min_value ?? undefined}
            max={param.constraint?.max_value ?? undefined}
            onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
            style={inputStyle}
          />
        );

      case "boolean":
        return (
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
            <input
              type="checkbox"
              checked={value === true || value === "true"}
              disabled={disabled}
              onChange={(e) => onChange(e.target.checked)}
            />
            {param.label}
          </label>
        );

      case "enum": {
        const enumValues = (param.constraint?.enum_values ?? []) as string[];
        return (
          <select
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            style={inputStyle}
          >
            <option value="">-- Select --</option>
            {enumValues.map((opt) => (
              <option key={String(opt)} value={String(opt)}>
                {String(opt)}
              </option>
            ))}
          </select>
        );
      }

      case "list": {
        const isComplex =
          param.constraint?.enum_values === undefined &&
          param.constraint?.min_items === undefined;
        const textValue = Array.isArray(value)
          ? (value as string[]).join("\n")
          : typeof value === "string"
            ? value
            : JSON.stringify(value, null, 2) ?? "";
        return (
          <div>
            {isComplex && (
              <div
                style={{
                  fontSize: 10,
                  color: "#64748b",
                  marginBottom: 2,
                }}
              >
                Custom JSON — or one item per line for simple string lists
              </div>
            )}
            <textarea
              value={textValue}
              disabled={disabled}
              rows={4}
              onChange={(e) => onChange(e.target.value)}
              style={{
                ...inputStyle,
                resize: "vertical",
                fontFamily: "monospace",
                fontSize: 11,
                lineHeight: 1.4,
              }}
              spellCheck={false}
            />
          </div>
        );
      }

      case "object": {
        const textValue =
          typeof value === "object" && value !== null
            ? JSON.stringify(value, null, 2)
            : String(value ?? "");
        return (
          <textarea
            value={textValue}
            disabled={disabled}
            rows={4}
            onChange={(e) => onChange(e.target.value)}
            style={{
              ...inputStyle,
              resize: "vertical",
              fontFamily: "monospace",
              fontSize: 11,
              lineHeight: 1.4,
            }}
            spellCheck={false}
          />
        );
      }

      default:
        return (
          <input
            type="text"
            value={String(value ?? "")}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            style={inputStyle}
          />
        );
    }
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 2,
        }}
      >
        <label
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "#1e293b",
          }}
        >
          {param.label}
          {param.required && (
            <span style={{ color: "#dc2626", marginLeft: 2 }}>*</span>
          )}
        </label>
        {param.help_text && (
          <span
            title={param.help_text}
            style={{
              fontSize: 10,
              color: "#94a3b8",
              cursor: "help",
            }}
          >
            ⓘ
          </span>
        )}
      </div>
      {renderControl()}
      {error && (
        <div style={{ fontSize: 10, color: "#dc2626", marginTop: 2 }}>
          {error}
        </div>
      )}
    </div>
  );
}
