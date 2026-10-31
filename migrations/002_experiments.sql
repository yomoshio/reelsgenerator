alter table jobs
    add column if not exists recipe     jsonb not null default '{}',
    add column if not exists experiment text,
    add column if not exists arm        text,
    add column if not exists parent     uuid,
    add column if not exists calls      jsonb not null default '[]',
    add column if not exists critique   jsonb,
    add column if not exists qa         jsonb,
    add column if not exists rating     int,
    add column if not exists metrics    jsonb;

create index if not exists jobs_by_experiment on jobs (experiment);
