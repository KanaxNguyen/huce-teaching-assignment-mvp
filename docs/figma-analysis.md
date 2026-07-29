# Figma analysis

Source: https://www.figma.com/design/OdSLKDuaAwEoQePRugRIA1

## Access status

The Figma connector is installed, but the file could not be enumerated. `get_metadata` and a read-only `use_figma` call both returned `INVALID_ARGUMENT`. Consequently, no page, frame, node ID, screenshot, color style, or logo asset is attributed to Figma.

## Implementation fallback: Option 02 — Minimal SaaS

The interface follows the characteristics explicitly supplied with the request:

- light, spacious SaaS layout;
- 232 px pale blue-gray sidebar and navy dark-mode sidebar;
- fine-line icons and a soft-blue selected item;
- white cards, subtle borders, 14–16 px radii, no gradients;
- compact tables with generous row height;
- responsive sidebar drawer below tablet width.

Design tokens are implemented in `apps/web/src/styles/design-tokens.css`. The typography uses Inter with system fallbacks. The primary brand color is an accessible institutional blue, treated as an implementation inference rather than a Figma-extracted value.

## Component inventory

- application shell, collapsible sidebar, top bar;
- metric card and status badge;
- upload dropzone and source-file list;
- validation issue table;
- class assignment table;
- constraint builder and seminar form;
- optimizer run panel;
- weekly timetable;
- conflict list and export dialog;
- loading, empty, and error states.

## HUCE logo

No logo could be verified in Figma. The app uses a text-only `HUCE` wordmark. It must be replaced with an official asset supplied by the university; no seal or unofficial image was recreated.

