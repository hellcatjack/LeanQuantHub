interface IdChipProps {
  label: string;
  value: number | string | null | undefined;
}

export default function IdChip({ label, value }: IdChipProps) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const text = `${label}#${value}`;

  return (
    <span className="id-chip" title={text}>
      <span className="id-chip-text">{text}</span>
    </span>
  );
}
