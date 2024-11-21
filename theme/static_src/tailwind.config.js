/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        // Update these paths to match your project structure
        '../../**/templates/**/*.html',  // This will catch all template files
        '../../**/templates/*.html',     // This will catch root template files
    ],
    theme: {
        extend: {
            fontFamily: {
                'space': ['Space Mono', 'monospace'],
            },
        },
    },
    plugins: [
        require('@tailwindcss/forms'),
        require('@tailwindcss/typography'),
        require('@tailwindcss/aspect-ratio'),
    ],
    safelist: [
        // InstantSearch classes
        'ais-SearchBox',
        'ais-SearchBox-form',
        'ais-SearchBox-input',
        'ais-SearchBox-submit',
        'ais-SearchBox-reset',
        'ais-SearchBox-submitIcon',
        'ais-SearchBox-resetIcon',
        'ais-RefinementList',
        'ais-RefinementList-searchBox',
        'ais-RefinementList-searchInput',
        'ais-RefinementList-list',
        'ais-RefinementList-item',
        'ais-RefinementList-label',
        'ais-RefinementList-checkbox',
        'ais-RefinementList-count',
        'ais-RefinementList-noResults',
        'ais-RefinementList-showMore',
        'ais-RefinementList-showMoreButton',
      ],
}
