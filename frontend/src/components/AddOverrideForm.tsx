import React from 'react';
import { formInputStyle, addButtonStyle, theme } from '../styles';

interface Props {
  overrideVar: string;
  overrideAction: string;
  overrideBinIds: string;
  overrideLabel: string;
  overrideReason: string;
  selectedVars: string[];
  onOverrideVarChange: (v: string) => void;
  onOverrideActionChange: (v: string) => void;
  onOverrideBinIdsChange: (v: string) => void;
  onOverrideLabelChange: (v: string) => void;
  onOverrideReasonChange: (v: string) => void;
  onAddOverride: () => void;
}

export function AddOverrideForm({
  overrideVar,
  overrideAction,
  overrideBinIds,
  overrideLabel,
  overrideReason,
  selectedVars,
  onOverrideVarChange,
  onOverrideActionChange,
  onOverrideBinIdsChange,
  onOverrideLabelChange,
  onOverrideReasonChange,
  onAddOverride,
}: Props) {
  return (
    <div
      style={{
        padding: 12,
        border: `1px solid ${theme.border}`,
        borderRadius: 6,
        backgroundColor: theme.surface,
        marginBottom: 16,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600, color: theme.text, marginBottom: 8 }}>
        Add Override
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <label style={{ fontSize: 11, color: theme.muted, flex: 1 }}>
            Variable
            <select
              value={overrideVar}
              onChange={(e) => onOverrideVarChange(e.target.value)}
              style={formInputStyle}
            >
              <option value="">—</option>
              {selectedVars.map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: 11, color: theme.muted, flex: 1 }}>
            Action
            <select
              value={overrideAction}
              onChange={(e) => onOverrideActionChange(e.target.value)}
              style={formInputStyle}
            >
              <option value="merge_bins">Merge Bins</option>
              <option value="group_categories">Group Categories</option>
              <option value="isolate_missing">Isolate Missing</option>
              <option value="isolate_special_value">Isolate Special Value</option>
            </select>
          </label>
        </div>
        <label style={{ fontSize: 11, color: theme.muted }}>
          Source Bin IDs (comma-separated)
          <input
            type="text"
            value={overrideBinIds}
            onChange={(e) => onOverrideBinIdsChange(e.target.value)}
            style={formInputStyle}
            placeholder="bin_0, bin_1, bin_2"
          />
        </label>
        <label style={{ fontSize: 11, color: theme.muted }}>
          New Label (optional, for merge/group)
          <input
            type="text"
            value={overrideLabel}
            onChange={(e) => onOverrideLabelChange(e.target.value)}
            style={formInputStyle}
            placeholder="e.g. Combined Low-Risk"
          />
        </label>
        <label style={{ fontSize: 11, color: theme.muted }}>
          Reason (required)
          <input
            type="text"
            value={overrideReason}
            onChange={(e) => onOverrideReasonChange(e.target.value)}
            style={formInputStyle}
            placeholder="Why this override is needed"
          />
        </label>
        <button onClick={onAddOverride} style={addButtonStyle}>
          Add Override
        </button>
      </div>
    </div>
  );
}
