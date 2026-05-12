import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

const HARD_CODED_TEXT_ATTRS = new Set(['aria-label', 'title', 'placeholder', 'alt'])
const RAW_COLOR_CLASS_PATTERN = /\b(?:bg-white|text-black)\b/
const RAW_COLOR_VALUE_PATTERN = /(?:#[0-9a-fA-F]{3,8}\b|rgba?\s*\()/
const HUMAN_TEXT_PATTERN = /[A-Za-z\u4E00-\u9FFF]/

const luminaRulesPlugin = {
  rules: {
    'no-hardcoded-ui-text': {
      meta: {
        type: 'suggestion',
        docs: {
          description:
            'Disallow hardcoded UI text in JSX and user-facing attributes.',
        },
        schema: [],
        messages: {
          hardcodedText:
            'Hardcoded UI text is not allowed. Use i18n key via t("...").',
        },
      },
      create(context) {
        const hasHumanText = (value) =>
          typeof value === 'string' &&
          HUMAN_TEXT_PATTERN.test(value) &&
          value.trim().length > 0

        return {
          JSXText(node) {
            const text = node.value
            if (!hasHumanText(text)) return
            context.report({ node, messageId: 'hardcodedText' })
          },
          JSXAttribute(node) {
            const attrName = node.name?.name
            if (!HARD_CODED_TEXT_ATTRS.has(attrName)) return
            if (!node.value) return
            if (node.value.type !== 'Literal') return
            if (!hasHumanText(node.value.value)) return
            context.report({ node, messageId: 'hardcodedText' })
          },
        }
      },
    },
    'no-raw-ui-colors': {
      meta: {
        type: 'suggestion',
        docs: {
          description:
            'Disallow raw UI colors and legacy utility colors in JSX.',
        },
        schema: [],
        messages: {
          rawColor:
            'Raw UI colors are not allowed here. Use semantic tokens or CSS vars.',
        },
      },
      create(context) {
        const checkText = (node, text) => {
          if (typeof text !== 'string') return
          if (
            RAW_COLOR_CLASS_PATTERN.test(text) ||
            RAW_COLOR_VALUE_PATTERN.test(text)
          ) {
            context.report({ node, messageId: 'rawColor' })
          }
        }

        const checkStyleObject = (node) => {
          if (!node || node.type !== 'ObjectExpression') return
          for (const prop of node.properties) {
            if (prop.type !== 'Property') continue
            const valueNode = prop.value
            if (valueNode?.type === 'Literal') {
              checkText(valueNode, valueNode.value)
            }
            if (
              valueNode?.type === 'TemplateLiteral' &&
              valueNode.expressions.length === 0
            ) {
              const text = valueNode.quasis.map((q) => q.value.cooked).join('')
              checkText(valueNode, text)
            }
          }
        }

        return {
          JSXAttribute(node) {
            const attrName = node.name?.name
            if (!node.value) return

            if (node.value.type === 'Literal') {
              const text = node.value.value
              if (attrName === 'className' || attrName === 'class' || attrName === 'style') {
                checkText(node, text)
              }
              return
            }

            if (
              node.value.type === 'JSXExpressionContainer' &&
              node.value.expression.type === 'TemplateLiteral' &&
              node.value.expression.expressions.length === 0 &&
              (attrName === 'className' || attrName === 'class')
            ) {
              const text = node.value.expression.quasis
                .map((q) => q.value.cooked)
                .join('')
              checkText(node, text)
              return
            }

            if (
              attrName === 'style' &&
              node.value.type === 'JSXExpressionContainer'
            ) {
              checkStyleObject(node.value.expression)
            }
          },
        }
      },
    },
  },
}

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      lumina: luminaRulesPlugin,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        {
          allowConstantExport: true,
          allowExportNames: [
            'useI18n',
            'resolvePreviewLineLeft',
            'classifyHue',
            'matchesSearch',
            'SLICER_BRAND_COLORS',
            'getSlicerBrandStyle',
            'getButtonLabel',
            'getSlicerLinkHint',
            'clampScale',
            'computeZoomTranslate',
            'buildFileUrl',
            'computeCenterOffset',
            'computeFitDistance',
            'createKeychainRingGeometry',
            'resetKeychainRingGeometryDisposeForTests',
            'computeLoopPosition',
            'rasterizeMeshToGrid',
            'rasterizeMeshesToGrid',
            'dilateGrid',
            'createRingMask',
            'greedyRectMerge',
            'extrudeRectangles',
            'offsetContour',
            'createOutlineRingGeometry',
            'extractBoundaryContour',
            'resetOutlineFrameGeometryDisposeForTests',
            'rasterizeColorMeshesToGrid',
            'resetCloisonneWireGeometryDisposeForTests',
            'detectColorEdges',
            'createSolidMask',
            'maskIntersection',
            'extractHexFromMeshName',
            'toggleColorSelection',
            'buildHuePeakProfile',
            'buildHueLightnessPoints',
            'buildHueChromaPoints',
            'clearLabPointCloud3DHullCacheForTests',
            'deriveBounds',
            'getPointRadius',
            'formatNumberRange',
            'isLutSubTab',
            'isMaterialSubTab',
            'resolvePrimaryTab',
            'hasSubTabs',
          ],
        },
      ],
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: [
      'src/**/*.test.ts',
      'src/**/*.test.tsx',
      'src/**/*.property.test.ts',
      'src/**/*.property.test.tsx',
      'src/**/__tests__/**',
      'src/i18n/translations.ts',
      'src/theme/**',
      'src/components/themeConfig.ts',
      'src/components/lightingConfig.ts',
    ],
    rules: {
      'lumina/no-hardcoded-ui-text': 'warn',
      'lumina/no-raw-ui-colors': 'warn',
    },
  },
)
