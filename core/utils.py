class AlgoliaPaginator:
    """Helper class to make Algolia results work with Django templates"""
    def __init__(self, algolia_response):
        self.hits = algolia_response['hits']
        self.page = algolia_response['page'] + 1  # Convert from 0-based to 1-based
        self.has_previous = self.page > 1
        self.has_next = self.page * algolia_response['hitsPerPage'] < algolia_response['nbHits']
        self.number = self.page
        self.paginator = type('AlgoliaPaginatorInfo', (), {
            'num_pages': -(-algolia_response['nbHits'] // algolia_response['hitsPerPage']),  # Ceiling division
            'count': algolia_response['nbHits']
        })

    def __iter__(self):
        return iter(self.hits)

    def __getitem__(self, key):
        return self.hits[key]

    @classmethod
    def from_algolia_response(cls, response):
        return cls(response)