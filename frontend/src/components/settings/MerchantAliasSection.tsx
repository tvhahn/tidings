import { useState, useMemo } from "react";
import {
  AddRowButton,
  DeleteRowButton,
  ListSearchInput,
  ShowAllToggle,
} from "@/components/settings/managedListPrimitives";
import { SettingsSectionHeader } from "@/components/settings/SettingsSectionHeader";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useMerchantAliases,
  usePutMerchantAlias,
  useDeleteMerchantAlias,
} from "@/hooks/useMerchantAliases";

export function MerchantAliasSection() {
  const { data, isLoading } = useMerchantAliases();
  const putMutation = usePutMerchantAlias();
  const deleteMutation = useDeleteMerchantAlias();

  const [aliasSearch, setAliasSearch] = useState("");
  const [newRaw, setNewRaw] = useState("");
  const [newCanonical, setNewCanonical] = useState("");
  const [aliasesExpanded, setAliasesExpanded] = useState(false);

  const aliases = useMemo(() => data?.aliases ?? [], [data?.aliases]);

  const filtered = useMemo(() => {
    if (!aliasSearch) return aliases;
    const q = aliasSearch.toLowerCase();
    return aliases.filter(
      (a) => a.raw_name.includes(q) || a.canonical_name.toLowerCase().includes(q)
    );
  }, [aliases, aliasSearch]);

  const handleAdd = () => {
    const raw = newRaw.trim();
    const canonical = newCanonical.trim();
    if (!raw || !canonical) return;
    putMutation.mutate(
      { rawName: raw, canonicalName: canonical },
      {
        onSuccess: () => {
          setNewRaw("");
          setNewCanonical("");
        },
      }
    );
  };

  const COLLAPSED_LIMIT = 4;
  const isSearching = aliasSearch.length > 0;
  const showAll = isSearching || aliasesExpanded;
  const visible = showAll ? filtered : filtered.slice(0, COLLAPSED_LIMIT);
  const hiddenCount = filtered.length - COLLAPSED_LIMIT;

  return (
    <section className="space-y-4">
      <SettingsSectionHeader
        title="Merchant Aliases"
        infoHint={{
          label: "About Merchant Aliases",
          content:
            "Display-name overrides for raw bank descriptions on the Income Statement. Purely cosmetic — the stored transaction record and its category are unchanged.",
        }}
        count={data?.count}
        countLabel="merchant aliases"
        toolbar={
          <ListSearchInput
            id="settings-aliases-search"
            value={aliasSearch}
            onChange={setAliasSearch}
            ariaLabel="Search merchant aliases"
            placeholder="Search aliases…"
          />
        }
      />

      <p className="text-sm text-muted-foreground">
        Map raw merchant names to canonical display names for the Income Statement.
      </p>

      {/* Add alias form */}
      <div className="flex flex-col gap-2 rounded-lg border border-border/50 bg-muted/20 px-3 py-2 sm:flex-row sm:items-center">
        <Input
          id="settings-aliases-new-raw"
          placeholder="Raw name"
          value={newRaw}
          onChange={(e) => setNewRaw(e.target.value)}
          className="h-8 flex-1 bg-background"
        />
        <Input
          id="settings-aliases-new-canonical"
          placeholder="Display name"
          value={newCanonical}
          onChange={(e) => setNewCanonical(e.target.value)}
          className="h-8 flex-1 bg-background"
          onKeyDown={(e) => {
            if (e.key === "Enter") handleAdd();
          }}
        />
        <AddRowButton
          onClick={handleAdd}
          disabled={!newRaw.trim() || !newCanonical.trim() || putMutation.isPending}
          label="Add alias"
        />
      </div>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}

      {!isLoading && filtered.length === 0 && (
        <p className="py-6 text-center text-muted-foreground">
          {aliasSearch ? "No aliases match your search" : "No merchant aliases configured"}
        </p>
      )}

      {!isLoading && visible.length > 0 && (
        <div className="space-y-2">
          <div className="rounded-xl border border-border/50">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Raw Name</TableHead>
                  <TableHead>Display Name</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((a) => (
                  <TableRow key={a.raw_name}>
                    <TableCell>
                      <span className="font-medium text-sm">{a.raw_name}</span>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm">{a.canonical_name}</span>
                    </TableCell>
                    <TableCell>
                      <DeleteRowButton
                        onClick={() => deleteMutation.mutate(a.raw_name)}
                        disabled={deleteMutation.isPending}
                        label="Delete alias"
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {!isSearching && hiddenCount > 0 && (
            <ShowAllToggle
              expanded={aliasesExpanded}
              onToggle={() => setAliasesExpanded(!aliasesExpanded)}
              totalCount={filtered.length}
              entityPlural="aliases"
            />
          )}
        </div>
      )}
    </section>
  );
}
