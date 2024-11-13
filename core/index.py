import algoliasearch_django as algoliasearch

from .models import Journalist

algoliasearch.register(Journalist)