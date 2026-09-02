# canoe-electricity — Refactor Decision Log

Per the design document (Section 13), each ambiguous `(?)` table encountered
during the stage-2 refactor is recorded here: what was ambiguous, what this
module does, and any follow-ups required.

---

### `planning_reserve_margin`

- **Question:** Is this a cross-sector policy parameter or an electricity-specific one?
- **Decision:** `canoe-electricity` owns it. The planning reserve margin is an
  electric-sector concept (minimum dispatchable capacity headroom over peak load
  by region and period). No other sector module needs to write to this table.
- **Owner/rationale:** Decided during stage-2 refactor (2026-06-30). CODERS
  `CA_system_parameters` provides `reserve_requirements_percent` per province,
  and the electricity module is the only consumer of this data.
- **Follow-ups:** None.

---

### Emission commodities in `commodity` (co2, co2e, so2, nox, hg)

- **Question:** Should emission commodity rows (co2, co2e, so2, nox, hg) be
  defined by this module, or should they be global rows seeded by canoe-base?
- **Decision:** For now, `canoe-electricity` writes each emission commodity it
  uses via `INSERT OR IGNORE`, using a module-namespaced commodity code
  (or shared code if the schema requires uniqueness). This avoids blocking on a
  canoe-base change.
- **Owner/rationale:** Temporary. Emission commodities are genuinely cross-sector
  (agriculture, industry, and residential also emit CO2e). The long-term answer
  is canoe-base seeding these rows so every module can reference them without
  writing them.
- **Follow-ups:** File a canoe-base request to seed the standard emission
  commodity rows (`co2`, `co2e`, `so2`, `nox`, `hg`) so sector modules can
  drop their own writes. Revisit when a second module also writes emission
  activity rows.

---

### `tech_group` / `tech_group_member` / `tech_group_label`

- **Question:** Policy groupings like "all renewables" or "clean electricity"
  may span sectors. Who owns the group row and member rows?
- **Decision:** `canoe-electricity` defines and owns all tech groups it uses
  (e.g. renewable generation, clean electricity for RPS purposes) via
  `INSERT OR IGNORE`. Groups are namespaced with an `E_` prefix to avoid
  collisions. If a future cross-sector group is needed, it can be promoted to
  canoe-base at that time.
- **Owner/rationale:** Decided during stage-2 refactor (2026-06-30). All
  current tech groups in this module reference only electricity technologies;
  no other sector has contributed members yet.
- **Follow-ups:** Revisit when `canoe-fuel` or another module needs to add
  members to an electricity-defined group (e.g. hydrogen from electrolysis in a
  clean energy grouping).

---

### `linked_tech`

- **Question:** CCS retrofit technologies link an electricity generator's
  intermediate output commodity to a carbon-capture process. Does electricity
  own this link, or is it shared with `canoe-fuel`?
- **Decision:** Deferred. `canoe-electricity` currently does not write to
  `linked_tech`. The CCS retrofit structure uses an intermediate commodity
  and a bypass technology rather than `linked_tech` rows (see
  `generators.py::aggregate_ccs_retrofits`). If `linked_tech` becomes
  necessary (e.g. for power-to-gas connections with `canoe-fuel`), the decision
  of ownership must be made jointly with the `canoe-fuel` refactor.
- **Owner/rationale:** Decided during stage-2 refactor (2026-06-30).
- **Follow-ups:** Flag for `canoe-fuel` refactor: check whether any
  `linked_tech` rows are needed to connect electricity output commodities to
  fuel-side processes.

---

### `limit_activity_share` (formerly `rps_requirement`)

- **Question:** RPS / clean-electricity share constraints compare tech groups
  and may reference technologies from multiple sectors in future.
- **Decision:** `canoe-electricity` writes these rows scoped to electricity
  tech groups only. The deprecated `rps_requirement` table is not written;
  `limit_activity_share` is used exclusively.
- **Owner/rationale:** All current RPS targets reference electricity generation
  groups. Cross-sector share constraints are out of scope for this round.
- **Follow-ups:** None for this round.
