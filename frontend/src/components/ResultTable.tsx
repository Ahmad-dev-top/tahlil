import { cn } from "@/lib/cn";
import { formatCell, isNumericColumn } from "@/lib/format";
import type { Row } from "@/lib/types";

export function ResultTable({ columns, rows, maxRows = 50 }: { columns: string[]; rows: Row[]; maxRows?: number }) {
  const shown = rows.slice(0, maxRows);
  const numeric = Object.fromEntries(columns.map((c) => [c, isNumericColumn(shown, c)]));
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-max min-w-full border-collapse text-sm">
        <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-900">
          <tr>
            {columns.map((c) => (
              <th
                key={c}
                className={cn(
                  "whitespace-nowrap border-b border-zinc-200 px-3 py-2 font-semibold dark:border-zinc-800",
                  numeric[c] ? "text-right" : "text-left",
                )}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className="odd:bg-white even:bg-zinc-50/60 dark:odd:bg-transparent dark:even:bg-zinc-900/40">
              {columns.map((c) => (
                <td
                  key={c}
                  className={cn(
                    "whitespace-nowrap border-b border-zinc-100 px-3 py-1.5 dark:border-zinc-800/60",
                    numeric[c] && "text-right tabular-nums",
                  )}
                >
                  {formatCell(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
