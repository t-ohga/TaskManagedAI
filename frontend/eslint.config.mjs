import nextPlugin from "@next/eslint-plugin-next";
import jsxA11yPlugin from "eslint-plugin-jsx-a11y";
import reactPlugin from "eslint-plugin-react";
import reactHooksPlugin from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

const tsRuleConfigs = [...tseslint.configs.strict, ...tseslint.configs.stylistic];
const tsRules = Object.assign(
  {},
  ...tsRuleConfigs.map((config) => config.rules ?? {})
);

export default [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "coverage/**",
      "playwright-report/**",
      "test-results/**"
    ],
    linterOptions: {
      reportUnusedDisableDirectives: "error"
    }
  },
  {
    files: ["eslint.config.mjs"],
    languageOptions: {
      globals: globals.node,
      sourceType: "module"
    }
  },
  {
    files: ["postcss.config.js"],
    languageOptions: {
      globals: globals.node,
      sourceType: "commonjs"
    }
  },
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        ecmaFeatures: {
          jsx: true
        },
        sourceType: "module"
      },
      globals: {
        ...globals.browser,
        ...globals.node
      }
    },
    plugins: {
      "@next/next": nextPlugin,
      "@typescript-eslint": tseslint.plugin,
      "jsx-a11y": jsxA11yPlugin,
      react: reactPlugin,
      "react-hooks": reactHooksPlugin
    },
    settings: {
      next: {
        rootDir: ["./"]
      },
      react: {
        version: "detect"
      }
    },
    rules: {
      ...tsRules,
      ...nextPlugin.configs["core-web-vitals"].rules,
      ...reactPlugin.configs.flat.recommended.rules,
      ...reactPlugin.configs.flat["jsx-runtime"].rules,
      ...reactHooksPlugin.configs.flat.recommended.rules,
      ...jsxA11yPlugin.flatConfigs.recommended.rules,
      "@typescript-eslint/consistent-type-definitions": ["error", "type"],
      "@typescript-eslint/consistent-type-imports": [
        "error",
        {
          fixStyle: "inline-type-imports",
          prefer: "type-imports"
        }
      ],
      "@typescript-eslint/no-explicit-any": "error",
      "react/jsx-no-leaked-render": [
        "error",
        {
          validStrategies: ["ternary"]
        }
      ],
      "react/prop-types": "off"
    }
  }
];

