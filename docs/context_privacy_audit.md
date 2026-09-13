# Context privacy audit

Scope: application/website discovery, rule editing, protection events, logs,
diagnostics, and the Dashboard bridge. This audit does not claim that operating
system accessibility services or unrelated model libraries never log data.

| Boundary | Data retained or exposed | Guardrail |
| --- | --- | --- |
| Native website reader → Context | Normalized hostname in memory | Address-bar value is reduced before `WebsiteContext` is published; reader exceptions are discarded. |
| Context → SQLite rules | User-configured application identifiers and website hostnames | `RuleSettingsStore` normalizes before saving. A URL path, query, or fragment is not stored. |
| Context → diagnostics | Availability, browser/website state, rule actions, effective policy | No application identifier, hostname, window title, or URL in the ordinary diagnostics snapshot or Dashboard IPC. |
| Context Policy → Vision | Rule actions only | `VisualDecisionEngine` never receives hostname, application name, URL, or medical/art/education flags. Missing context still runs Vision. |
| Rule trigger → SQLite history | Trigger type, time, monitor, intervention flag | New `application_rule` and `website_rule` records always have a null label. Historical `blocklist` rows are masked on read. |
| SQLite history → Dashboard/CLI | Event metadata | Labels on these trigger types are masked on read, including for records written by older versions. |
| Legacy window reader → log | Fixed failure message | Native exception text and traceback are not logged; they may contain a title or address. |

Application and website policy uses `ContextPolicyService` only. Window-title
substring matching is not a product path.

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
