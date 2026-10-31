# Business Rules
R1  next_due_date = calibration_date + plan.interval_days
R2  An asset is "valid" from its latest PASS calibration until next_due_date
    (+ grace_days, + any approved emergency extension).
R3  Use status:
    - VALID                   : used inside the valid window
    - OVERDUE_ALLOWED         : overdue, but plan.block_if_overdue = false
    - OVERDUE_WITH_EXCEPTION  : overdue, blocked by policy, but an approved extension exists
    - BLOCKED                 : overdue, blocked by policy, system stopped the use
    - VIOLATION               : overdue, blocked by policy, no exception, and used anyway
R4  A FAIL calibration creates: a CORRECTIVE_ACTION work order (with downtime),
    an IMPACT_ASSESSMENT work order, a CALIBRATION_FAILED alert, and an
    ASSET_STATUS_CHANGE audit record (ACTIVE -> QUARANTINED).
R5  Each completed calibration gets CERT-<calibration_id>.
    A "certificate gap" = an event with no certificate.
R6  History is never overwritten. Every status change is a new AuditRecord row.

R2b A FAIL calibration does NOT move the due date. Only a PASS does. After a FAIL the asset is re-tested 3-14 days later.
R3b BLOCKED vs VIOLATION: if the asset's production line has an interlock (LINE-01..LINE-08) the system stops the overdue use (BLOCKED). On lines without one (LINE-09..LINE-12) the use goes ahead (VIOLATION).
R7  An asset is never used on a calibration day or while QUARANTINED.