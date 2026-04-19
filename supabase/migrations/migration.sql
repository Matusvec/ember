-- ============================================================
-- Axis — Supabase Schema
-- ============================================================
-- amir: what we use for the CV pipeline discovery runs, user profiles, and input mapping configs.
-- ── users ────────────────────────────────────────────────────
-- Extends auth.users with display info.


create table public.users (
  id          uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  created_at  timestamptz not null default now()
);

alter table public.users enable row level security;

create policy "users: read own"
  on public.users for select
  using (auth.uid() = id);

create policy "users: insert own"
  on public.users for insert
  with check (auth.uid() = id);

create policy "users: update own"
  on public.users for update
  using (auth.uid() = id);


-- ── movements ────────────────────────────────────────────────
-- Reference/lookup table of all known movement types.
-- CV pipeline matches detected signals against this table.
create table public.movements (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,        -- e.g. "head_tilt_left"
  body_region text not null,               -- e.g. "head", "eyes", "mouth", "hands", "shoulders"
  description text,
  created_at  timestamptz not null default now()
);

alter table public.movements enable row level security;

-- movements are global reference data — everyone can read
create policy "movements: read all"
  on public.movements for select
  using (true);

-- seed known movement types
insert into public.movements (name, body_region, description) values
  ('head_tilt_left',       'head',      'Head tilts to the left'),
  ('head_tilt_right',      'head',      'Head tilts to the right'),
  ('head_nod_up',          'head',      'Head nods upward'),
  ('head_nod_down',        'head',      'Head nods downward'),
  ('head_rotate_left',     'head',      'Head rotates left'),
  ('head_rotate_right',    'head',      'Head rotates right'),
  ('blink_left',           'eyes',      'Left eye blink'),
  ('blink_right',          'eyes',      'Right eye blink'),
  ('blink_both',           'eyes',      'Both eyes blink'),
  ('gaze_left',            'eyes',      'Sustained gaze to the left'),
  ('gaze_right',           'eyes',      'Sustained gaze to the right'),
  ('gaze_up',              'eyes',      'Sustained gaze upward'),
  ('gaze_down',            'eyes',      'Sustained gaze downward'),
  ('eyebrow_raise_left',   'eyes',      'Left eyebrow raise'),
  ('eyebrow_raise_right',  'eyes',      'Right eyebrow raise'),
  ('eyebrow_raise_both',   'eyes',      'Both eyebrows raise'),
  ('eyebrow_furrow',       'eyes',      'Eyebrows furrow together'),
  ('mouth_open',           'mouth',     'Mouth opens'),
  ('mouth_smile',          'mouth',     'Smile'),
  ('mouth_corner_left',    'mouth',     'Mouth corner pull left'),
  ('mouth_corner_right',   'mouth',     'Mouth corner pull right'),
  ('cheek_puff',           'mouth',     'Cheek puff'),
  ('shoulder_shrug_left',  'shoulders', 'Left shoulder shrug'),
  ('shoulder_shrug_right', 'shoulders', 'Right shoulder shrug'),
  ('shoulder_shrug_both',  'shoulders', 'Both shoulders shrug'),
  ('lean_left',            'body',      'Upper body lean left'),
  ('lean_right',           'body',      'Upper body lean right'),
  ('lean_forward',         'body',      'Upper body lean forward'),
  ('finger_extend_index',  'hands',     'Index finger extension'),
  ('finger_extend_middle', 'hands',     'Middle finger extension'),
  ('fist',                 'hands',     'Hand forms a fist'),
  ('wrist_rotate',         'hands',     'Wrist rotation');


-- ── calibration_sessions ─────────────────────────────────────
-- One session = one 90-second discovery run per user.
create type calibration_status as enum ('in_progress', 'completed', 'abandoned');

create table public.calibration_sessions (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.users(id) on delete cascade,
  status      calibration_status not null default 'in_progress',
  started_at  timestamptz not null default now(),
  completed_at timestamptz
);

create index on public.calibration_sessions (user_id);

alter table public.calibration_sessions enable row level security;

create policy "calibration_sessions: own"
  on public.calibration_sessions for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- ── cv_frames ────────────────────────────────────────────────
-- Raw frame data streamed in from the CV pipeline.
-- landmarks: full MediaPipe output (face mesh, pose, hands) as JSONB.
-- detected_movement_id: nullable — set once the pipeline matches a movement.
create table public.cv_frames (
  id                   uuid primary key default gen_random_uuid(),
  session_id           uuid not null references public.calibration_sessions(id) on delete cascade,
  user_id              uuid not null references public.users(id) on delete cascade,
  captured_at          timestamptz not null default now(),
  landmarks            jsonb not null,          -- raw MediaPipe landmark coordinates
  detected_movement_id uuid references public.movements(id),
  confidence           float check (confidence >= 0 and confidence <= 1),
  frame_index          integer                  -- sequential frame number within session
);

create index on public.cv_frames (session_id);
create index on public.cv_frames (user_id);
create index on public.cv_frames (detected_movement_id);

alter table public.cv_frames enable row level security;

create policy "cv_frames: own"
  on public.cv_frames for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);


-- ── input_mappings ───────────────────────────────────────────
-- User's confirmed gesture → keyboard/mouse action config.
-- action_type: e.g. "mouse_move", "left_click", "keyboard_key", "macro"
-- action_value: e.g. "cursor_left", "ArrowUp", "ctrl+c"
create table public.input_mappings (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id) on delete cascade,
  movement_id   uuid not null references public.movements(id),
  action_type   text not null,
  action_value  text not null,
  created_at    timestamptz not null default now(),
  unique (user_id, movement_id)   -- one action per movement per user
);

create index on public.input_mappings (user_id);

alter table public.input_mappings enable row level security;

create policy "input_mappings: own"
  on public.input_mappings for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
