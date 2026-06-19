export interface SafeConstraint {
  required: boolean;
  min_value?: number;
  max_value?: number;
  exclusive_min?: number;
  exclusive_max?: number;
  min_length?: number;
  max_length?: number;
  min_items?: number;
  max_items?: number;
  enum_values?: unknown[];
  pattern?: string | null;
}

export interface SafeDefinition {
  name: string;
  label: string;
  kind: string;
  default: unknown;
  required: boolean;
  constraint: SafeConstraint | null;
  help_text: string;
  group: string;
}

export interface SafeMethod {
  id: string;
  label: string;
  status: "available" | "coming_soon";
  params: SafeDefinition[];
  description: string;
}

export interface SafeSchema {
  node_type: string;
  version: string;
  title: string;
  methods: SafeMethod[];
  params_schema: Record<string, unknown>;
  defaults: Record<string, unknown>;
  description: string;
}
