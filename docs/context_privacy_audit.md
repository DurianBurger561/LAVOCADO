# Context privacy audit

Scope: application/website discovery, rule editing, protection events, logs,
diagnostics, and the Dashboard bridge. This audit does not claim that operating
system accessibility services or unrelated model libraries never log data.

| Boundary | Data retained or exposed | Guardrail |
| --- | --- | --- |
| Native website reader → Context | Normalized hostname in memory | Address-bar value is reduced before `WebsiteContext` is published; reader exceptions are discarded. |
| Context → SQLite rules | User-configured application identifiers and website hostnames | `RuleSettingsStore` normalizes before saving. A URL path, query, or fragment is not stored. |
| Context → diagnostics | Availability, browser/website state, rule actions, effective policy | No application identifier, hostname, window title, or URL in the ordinary diagnostics snapshot or Dashboard IPC. |
| Context Policy → Vision | Rule actions only | `DecisionEngine` never receives hostname, application name, URL, or medical/art/education flags. Missing context still runs Vision. |
| Rule trigger → SQLite history | Trigger type, time, monitor, intervention flag | Only `vision` events may store a detector label; all other trigger types have a null label on write. |
| SQLite history → Dashboard/CLI | Event metadata | Labels on non-vision trigger types are masked on read, without altering stored rows. |
| Native window reader → log | Fixed failure message | Native exception text and traceback are not logged; they may contain a title or address. |

Application and website policy uses `ContextPolicyService` only. Window-title
substring matching is not a product path.

Automated checks cover URL normalization, rule persistence, diagnostics,
native-reader error handling, event writes, and privacy-safe event reads.
