-- ============================================================
-- Sample services for demo / testing
-- ============================================================

INSERT INTO services (name, url, check_interval, is_active, tags, custom_headers, check_method, check_body)
VALUES
    ('HTTPBin',          'https://httpbin.org/get',     30, TRUE, ARRAY['production', 'external'], '{}', 'GET', NULL),
    ('JSONPlaceholder',  'https://jsonplaceholder.typicode.com/posts/1', 30, TRUE, ARRAY['staging', 'external'], '{}', 'GET', NULL),
    ('GitHub Status',    'https://www.githubstatus.com/api/v2/status.json', 60, TRUE, ARRAY['production', 'monitoring'], '{"Accept": "application/json"}', 'HEAD', NULL),
    ('HTTPBin POST',     'https://httpbin.org/post',    30, TRUE, ARRAY['staging', 'external'], '{"Content-Type": "application/json"}', 'POST', '{"health": true}'),
    ('Google DNS TCP',   'dns.google:443',              60, TRUE, ARRAY['production', 'infrastructure'], '{}', 'TCP', NULL),
    ('Monitor API',      'http://api:8000/metrics',     30, TRUE, ARRAY['production', 'internal'], '{}', 'GET', NULL),
    ('Monitor Frontend', 'monitor-frontend:80',         30, TRUE, ARRAY['production', 'internal'], '{}', 'TCP', NULL),
    ('RabbitMQ',         'monitor-rabbitmq:5672',       30, TRUE, ARRAY['production', 'internal'], '{}', 'TCP', NULL),
    ('Postgres DB',      'monitor-postgres:5432',       30, TRUE, ARRAY['production', 'internal'], '{}', 'TCP', NULL);
