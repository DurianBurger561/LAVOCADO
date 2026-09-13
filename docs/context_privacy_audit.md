# Context privacy audit

Scope: application/website discovery, rule editing, protection events, logs,
diagnostics, and the Dashboard bridge. This audit does not claim that operating
system accessibility services or unrelated model libraries never log data.

| Boundary | Data retained or exposed | Guardrail |
| --- | --- | --- |
| Native website reader → Context | Normalized hostname in memory | Address-bar value is reduced before `WebsiteContext` is published; reader exceptions are discarded. |
| Context → SQLite rules | User-configured application identifiers and website hostnames | `RuleSettingsStore` normalizes before saving. A URL path, query, or fragment is not stored. |
| Context → diagnostics | Availability, browser/website state, rule actions, effective policy | No application identifier, hostname, window title, or URL in the ordinary diagnostics snapshot or Dashboard IPC. |
| Rule or legacy-window trigger → SQLite history | Trigger type, time, monitor, intervention flag | New `application_rule`, `website_rule`, and `blocklist` records always have a null label. |
| SQLite history → Dashboard/CLI | Event metadata | Labels on these trigger types are masked on read, including for records written by older versions. |
| Legacy window reader → log | Fixed failure message | Native exception text and traceback are not logged; they may contain a title or address. |

The legacy `BLOCKED_APPS` matcher still compares window titles in memory for
terms that cannot be migrated to stable application identifiers. It does not
publish the matched term in a protection result or new event record.

Existing `events.db` files may contain labels from older versions. This change
does not delete or rewrite them. To count affected rows without displaying
private values, run this read-only SQL against your own `events.db`:

```sql
SELECT trigger_type, COUNT(*)
FROM protection_events
WHERE trigger_type IN ('application_rule', 'website_rule', 'blocklist')
  AND label IS NOT NULL
GROUP BY trigger_type;
```

Automated checks cover URL normalization, rule persistence, diagnostics,
native-reader error handling, new event writes, and masking of old event reads.
