"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  getDatasheetExtractionSchema,
  getDatasheetTemplate,
  listDatasheetTemplates,
  updateDatasheetTemplate,
} from "@/lib/api";
import type {
  DatasheetColumnKind,
  DatasheetExtractionSchema,
  DatasheetSourceHint,
  DatasheetTemplateColumn,
  DatasheetTemplateDetail,
  DatasheetTemplateSummary,
} from "@/types";
import AdminHeader from "./AdminHeader";

const KINDS: DatasheetColumnKind[] = [
  "bibliographic",
  "free_text",
  "controlled",
  "numeric",
];

const SOURCE_HINTS: DatasheetSourceHint[] = [
  "metadata",
  "abstract",
  "fulltext",
  "any",
];

/** Draft column — mirrors the API payload, minus the server-assigned id. */
type DraftColumn = Omit<DatasheetTemplateColumn, "id"> & { id?: string };

function toDraft(column: DatasheetTemplateColumn): DraftColumn {
  return { ...column };
}

function blankColumn(orderIndex: number): DraftColumn {
  return {
    key: "",
    label: "",
    kind: "free_text",
    order_index: orderIndex,
    vocabulary: [],
    extraction_hint: "",
    source_hint: "any",
    required: false,
    enabled: true,
  };
}

/** Reindex from 0 so order_index stays dense and unique — the API rejects gaps'
 * siblings (duplicates), and dense indices keep reordering predictable. */
function reindex(columns: DraftColumn[]): DraftColumn[] {
  return columns.map((column, index) => ({ ...column, order_index: index }));
}

function localValidationError(columns: DraftColumn[]): string | null {
  if (columns.length === 0) return "A template needs at least one column.";
  if (!columns.some((column) => column.enabled)) {
    return "At least one column must be enabled.";
  }
  for (const column of columns) {
    if (!column.key.trim()) return "Every column needs a key.";
    if (!/^[a-z][a-z0-9_]*$/.test(column.key)) {
      return `Key "${column.key}" must be snake_case (lower-case letters, digits and underscores, starting with a letter).`;
    }
    if (!column.label.trim()) return `Column "${column.key}" needs a label.`;
    if (column.kind === "controlled" && column.vocabulary.length === 0) {
      return `Column "${column.key}" is controlled and needs a vocabulary.`;
    }
  }
  const keys = columns.map((column) => column.key);
  const duplicate = keys.find((key, index) => keys.indexOf(key) !== index);
  if (duplicate) return `Duplicate column key "${duplicate}".`;
  return null;
}

export default function AdminDatasheetTemplatesClient() {
  const router = useRouter();
  const [templates, setTemplates] = useState<DatasheetTemplateSummary[]>([]);
  const [selectedName, setSelectedName] = useState("");
  const [detail, setDetail] = useState<DatasheetTemplateDetail | null>(null);
  const [columns, setColumns] = useState<DraftColumn[]>([]);
  const [schema, setSchema] = useState<DatasheetExtractionSchema | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void loadTemplates();
  }, []);

  useEffect(() => {
    if (selectedName) void loadDetail(selectedName);
  }, [selectedName]);

  function handleError(err: unknown, fallback: string) {
    if (err instanceof Error && err.message === "Unauthorized") {
      router.push("/login");
      return;
    }
    setError(err instanceof Error ? err.message : fallback);
  }

  async function loadTemplates() {
    try {
      setLoading(true);
      const data = await listDatasheetTemplates();
      setTemplates(data);
      setSelectedName((current) =>
        current && data.some((template) => template.name === current)
          ? current
          : data[0]?.name ?? ""
      );
      setError(null);
    } catch (err) {
      handleError(err, "Failed to load datasheet templates");
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(name: string) {
    try {
      const data = await getDatasheetTemplate(name);
      setDetail(data);
      setColumns(data.columns.map(toDraft));
      setSchema(null);
      setNotice(null);
      setError(null);
    } catch (err) {
      handleError(err, `Failed to load template ${name}`);
    }
  }

  function updateColumn(index: number, patch: Partial<DraftColumn>) {
    setColumns((current) =>
      current.map((column, i) => (i === index ? { ...column, ...patch } : column))
    );
  }

  function moveColumn(index: number, delta: number) {
    setColumns((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return reindex(next);
    });
  }

  function addColumn() {
    setColumns((current) => reindex([...current, blankColumn(current.length)]));
  }

  function removeColumn(index: number) {
    setColumns((current) => reindex(current.filter((_, i) => i !== index)));
  }

  async function handleSave() {
    if (!detail) return;
    const validationError = localValidationError(columns);
    if (validationError) {
      setError(validationError);
      setNotice(null);
      return;
    }
    try {
      setSaving(true);
      const saved = await updateDatasheetTemplate(detail.name, {
        columns: reindex(columns).map((column) => ({
          key: column.key.trim(),
          label: column.label.trim(),
          kind: column.kind,
          order_index: column.order_index,
          vocabulary: column.vocabulary,
          extraction_hint: column.extraction_hint?.trim() || null,
          source_hint: column.source_hint,
          required: column.required,
          enabled: column.enabled,
        })),
      });
      setDetail(saved);
      setColumns(saved.columns.map(toDraft));
      setSchema(null);
      setError(null);
      setNotice(`Saved. Template is now version ${saved.version}.`);
      await loadTemplates();
    } catch (err) {
      handleError(err, "Failed to save template");
    } finally {
      setSaving(false);
    }
  }

  async function handleShowSchema() {
    if (!detail) return;
    try {
      setSchema(await getDatasheetExtractionSchema(detail.name));
      setError(null);
    } catch (err) {
      handleError(err, "Failed to load extraction schema");
    }
  }

  const dirty = useMemo(() => {
    if (!detail) return false;
    return JSON.stringify(detail.columns.map(toDraft)) !== JSON.stringify(columns);
  }, [detail, columns]);

  return (
    <main className="min-h-screen bg-gray-50">
      <AdminHeader subtitle="Datasheet templates" />

      <section className="mx-auto grid max-w-6xl gap-6 px-6 py-6">
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {notice && (
          <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
            {notice}
          </div>
        )}

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Column set</h2>
              <p className="mt-1 max-w-2xl text-sm text-gray-500">
                These columns are the datasheet CSV header and the extraction contract.
                Adding a column adds a field to the schema sent to the model — no code
                change needed.
              </p>
            </div>
            <label className="grid gap-1 text-sm font-medium text-gray-700">
              Template
              <select
                value={selectedName}
                onChange={(event) => setSelectedName(event.target.value)}
                className="min-w-64 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-normal text-gray-900"
              >
                {templates.map((template) => (
                  <option key={template.name} value={template.name}>
                    {template.name} (v{template.version})
                  </option>
                ))}
              </select>
            </label>
          </div>

          {loading && <div className="mt-6 text-sm text-gray-500">Loading templates...</div>}

          {!loading && !detail && (
            <div className="mt-6 rounded-md border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
              No datasheet templates yet.
            </div>
          )}

          {detail && (
            <div className="mt-6 grid gap-4">
              <div className="grid gap-1 text-sm text-gray-600">
                <div>
                  <span className="font-medium text-gray-800">Version:</span>{" "}
                  {detail.version}
                  {detail.is_default && " · default"}
                </div>
                <div>
                  <span className="font-medium text-gray-800">Columns:</span>{" "}
                  {detail.column_count} ({detail.enabled_column_count} enabled)
                </div>
                {detail.description && (
                  <div className="max-w-3xl">
                    <span className="font-medium text-gray-800">Description:</span>{" "}
                    {detail.description}
                  </div>
                )}
              </div>

              <div className="overflow-x-auto rounded-md border border-gray-200">
                <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th scope="col" className="px-3 py-2 font-semibold text-gray-700">
                        #
                      </th>
                      <th scope="col" className="px-3 py-2 font-semibold text-gray-700">
                        Key
                      </th>
                      <th scope="col" className="px-3 py-2 font-semibold text-gray-700">
                        Label (CSV header)
                      </th>
                      <th scope="col" className="px-3 py-2 font-semibold text-gray-700">
                        Kind
                      </th>
                      <th scope="col" className="px-3 py-2 font-semibold text-gray-700">
                        Expected in
                      </th>
                      <th scope="col" className="px-3 py-2 font-semibold text-gray-700">
                        Vocabulary
                      </th>
                      <th scope="col" className="px-3 py-2 font-semibold text-gray-700">
                        Enabled
                      </th>
                      <th scope="col" className="px-3 py-2 font-semibold text-gray-700">
                        Order
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white">
                    {columns.map((column, index) => (
                      <tr key={column.id ?? `new-${index}`} className="align-top">
                        <td className="px-3 py-2 text-gray-500">{index + 1}</td>
                        <td className="px-3 py-2">
                          <input
                            aria-label={`Key for column ${index + 1}`}
                            value={column.key}
                            onChange={(event) =>
                              updateColumn(index, { key: event.target.value })
                            }
                            className="w-40 rounded-md border border-gray-300 px-2 py-1 font-mono text-xs text-gray-900"
                          />
                        </td>
                        <td className="px-3 py-2">
                          <input
                            aria-label={`Label for column ${index + 1}`}
                            value={column.label}
                            onChange={(event) =>
                              updateColumn(index, { label: event.target.value })
                            }
                            className="w-56 rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-900"
                          />
                        </td>
                        <td className="px-3 py-2">
                          <select
                            aria-label={`Kind for column ${index + 1}`}
                            value={column.kind}
                            onChange={(event) =>
                              updateColumn(index, {
                                kind: event.target.value as DatasheetColumnKind,
                              })
                            }
                            className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900"
                          >
                            {KINDS.map((kind) => (
                              <option key={kind} value={kind}>
                                {kind}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-3 py-2">
                          <select
                            aria-label={`Source hint for column ${index + 1}`}
                            value={column.source_hint}
                            onChange={(event) =>
                              updateColumn(index, {
                                source_hint: event.target.value as DatasheetSourceHint,
                              })
                            }
                            className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900"
                          >
                            {SOURCE_HINTS.map((hint) => (
                              <option key={hint} value={hint}>
                                {hint}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-3 py-2">
                          <textarea
                            aria-label={`Vocabulary for column ${index + 1}`}
                            value={column.vocabulary.join("\n")}
                            onChange={(event) =>
                              updateColumn(index, {
                                vocabulary: event.target.value
                                  .split("\n")
                                  .map((item) => item.trim())
                                  .filter(Boolean),
                              })
                            }
                            rows={2}
                            placeholder={
                              column.kind === "controlled" ? "One value per line" : "n/a"
                            }
                            disabled={column.kind !== "controlled"}
                            className="w-56 rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-900 disabled:bg-gray-100"
                          />
                          {column.kind === "controlled" && (
                            <div className="mt-1 text-xs text-gray-500">
                              {column.vocabulary.length} values
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            aria-label={`Enabled for column ${index + 1}`}
                            checked={column.enabled}
                            onChange={(event) =>
                              updateColumn(index, { enabled: event.target.checked })
                            }
                          />
                        </td>
                        <td className="whitespace-nowrap px-3 py-2">
                          <button
                            type="button"
                            aria-label={`Move column ${index + 1} up`}
                            onClick={() => moveColumn(index, -1)}
                            disabled={index === 0}
                            className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 disabled:opacity-40"
                          >
                            ↑
                          </button>
                          <button
                            type="button"
                            aria-label={`Move column ${index + 1} down`}
                            onClick={() => moveColumn(index, 1)}
                            disabled={index === columns.length - 1}
                            className="ml-1 rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 disabled:opacity-40"
                          >
                            ↓
                          </button>
                          <button
                            type="button"
                            aria-label={`Remove column ${index + 1}`}
                            onClick={() => removeColumn(index)}
                            className="ml-1 rounded border border-red-200 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={addColumn}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100"
                >
                  Add column
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving || !dirty}
                  className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving ? "Saving..." : "Save column set"}
                </button>
                <button
                  type="button"
                  onClick={handleShowSchema}
                  className="rounded-md border border-blue-200 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50"
                >
                  Preview extraction schema
                </button>
                {dirty && (
                  <span className="text-xs text-amber-700">
                    Unsaved changes. The preview shows the saved template.
                  </span>
                )}
              </div>

              {schema && (
                <div className="grid gap-2">
                  <div className="text-sm text-gray-600">
                    Extraction schema for{" "}
                    <span className="font-medium text-gray-800">
                      {schema.template_name} v{schema.template_version}
                    </span>{" "}
                    — {schema.enabled_columns.length} enabled columns
                  </div>
                  <pre className="max-h-96 overflow-auto rounded-md border border-gray-200 bg-gray-900 p-4 text-xs text-gray-100">
                    {JSON.stringify(schema.json_schema, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
