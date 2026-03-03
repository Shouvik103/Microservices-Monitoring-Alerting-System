-- ============================================================
-- Sample services for demo / testing
-- ============================================================

INSERT INTO services (name, url, check_interval, is_active, tags, custom_headers)
VALUES
    ('HTTPBin',          'https://httpbin.org/get',     30, TRUE, ARRAY['production', 'external'], '{}'),
    ('JSONPlaceholder',  'https://jsonplaceholder.typicode.com/posts/1', 30, TRUE, ARRAY['staging', 'external'], '{}'),
    ('GitHub Status',    'https://www.githubstatus.com/api/v2/status.json', 60, TRUE, ARRAY['production', 'monitoring'], '{"Accept": "application/json"}');
