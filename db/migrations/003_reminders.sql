-- ============================================================
-- 003_reminders.sql
-- Reminder dedup + snooze tables (public schema), shared with
-- Smart Reminder. Idempotent: safe to run even if the Smart
-- Reminder deployment already created these.
-- Depends on public.vehicles (001_vehicles.sql in Master_DB_Postgres).
-- ============================================================

CREATE TABLE IF NOT EXISTS public.reminder_log (
    id             BIGSERIAL PRIMARY KEY,
    vehicle_id     BIGINT NOT NULL REFERENCES public.vehicles(id),
    expiry_field   TEXT NOT NULL,
    expiry_date    DATE NOT NULL,
    trigger_offset INT NOT NULL,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vehicle_id, expiry_field, expiry_date, trigger_offset)
);

CREATE TABLE IF NOT EXISTS public.reminder_snooze (
    id            SERIAL PRIMARY KEY,
    vehicle_id    BIGINT NOT NULL REFERENCES public.vehicles(id) ON DELETE CASCADE,
    expiry_field  VARCHAR(50) NOT NULL,
    snoozed_until DATE,            -- NULL = permanent ignore
    reason        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    TEXT,           -- user_id that requested the snooze
    UNIQUE (vehicle_id, expiry_field)
);

CREATE INDEX IF NOT EXISTS reminder_snooze_vehicle_field
    ON public.reminder_snooze (vehicle_id, expiry_field);
