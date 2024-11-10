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
}
