export default [
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: {
        AbortController: "readonly",
        document: "readonly",
        fetch: "readonly",
        HTMLCanvasElement: "readonly",
        Map: "readonly",
        navigator: "readonly",
        performance: "readonly",
        requestAnimationFrame: "readonly",
        cancelAnimationFrame: "readonly",
        ResizeObserver: "readonly",
        Set: "readonly",
        TextDecoder: "readonly",
        URLSearchParams: "readonly",
        window: "readonly",
      },
    },
    rules: { "no-undef": "error" },
  },
];
