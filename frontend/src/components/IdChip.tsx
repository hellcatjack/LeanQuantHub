import { useEffect, useState } from "react";

interface IdChipProps {
  label: string;
  value: number | string | null | undefined;
  copyLabel?: string;
}

export default function IdChip({ label, value, copyLabel = "Copy ID" }: IdChipProps) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const text = `${label}#${value}`;
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(String(value));
        setCopied(true);
        return;
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = window.setTimeout(() => setCopied(false), 1200);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <span className="id-chip" title={text}>
      <span className="id-chip-text">{text}</span>
      <button
        type="button"
        className="id-chip-copy"
        onClick={copy}
        aria-label={copyLabel}
      >
        {copied ? "OK" : "Copy"}
      </button>
    </span>
  );
}
