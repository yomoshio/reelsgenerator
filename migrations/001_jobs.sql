create table if not exists jobs (
    id          uuid primary key,
    idea        text        not null,
    status      text        not null default 'new',
    attempts    int         not null default 0,
    script      jsonb,
    assets      jsonb       not null default '{}',
    last_error  text,
    lease_until timestamptz,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists jobs_by_status on jobs (status, created_at);
