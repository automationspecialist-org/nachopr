DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 20,  # in seconds
            'pragmas': {
                'journal_mode': 'wal',     # Enable WAL
                'synchronous': 'normal',    # Can also use 'full' for more durability
                'cache_size': -64000,      # 64MB cache
                'foreign_keys': 1
            }
        }
    }
} 

AUTH_USER_MODEL = 'core.CustomUser'