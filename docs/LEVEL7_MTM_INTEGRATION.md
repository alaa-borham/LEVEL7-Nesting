# Working together with LEVEL7 MTM

LEVEL7 MTM (made-to-measure orders → GRAFIS order models) and LEVEL7 Nesting are separate programs, installed
and updated on their own. LEVEL7 MTM uses only this program's command line (`level7-cli.exe`) and the files
it writes; nothing here depends on LEVEL7 MTM.

What LEVEL7 MTM relies on (keep it stable — add fields, do not rename them):

* `level7-cli info --json FILE` — `{"format": "level7-info", "format_version": 1, "level7_version", "name",
  "size_names", "pieces": [{number, name, production, material, count, mirrored, sizes}], "issues",
  "features": ["remnant"]}` (`features`: options this version understands; LEVEL7 MTM passes them only then);
* `level7-cli nest FILE --width W --sizes KEY=QTY --time T [--remnant] -o OUT.l7n` — exit code 0 only for a
  valid marker, the JSON statistics on stdout (`length_mm`, `efficiency_total_width_pct`, `placed`, `unplaced`);
  `--remnant`: after nesting the small pieces are packed together so the fabric left over is one large piece
  (same length; only when the packed layout passes the check and the largest free rectangle grows);
* `level7-cli export OUT.l7n --format plt|iso|dxf [--plt-preset algotex_grafis] [--iso-preset bullmer_grafis] -o F`;
* `LEVEL7Nesting.exe FILE` opens FILE.

Order models written by LEVEL7 MTM have only their base size (`#GRDTAB` with one `__…` entry). Their one size
is listed as `base:<name>` in `size_names`, so a saved marker can be nested again from the window; a `.l7n`
saved before that (empty `size_names`) takes its size from `cut_order.size_quantities` when opened.
