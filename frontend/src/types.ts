export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface DatasetSummary {
  id: number;
  name: string;
  vendor?: string | null;
  asset_class?: string | null;
  region?: string | null;
  frequency?: string | null;
  coverage_start?: string | null;
  coverage_end?: string | null;
  source_path?: string | null;
  updated_at: string;
}
