import { createTheme } from '@mantine/core'

/** Mantine theme mapped onto the existing APEX-7 Bloomberg tokens. */
export const apexTheme = createTheme({
  fontFamily: "'IBM Plex Sans', sans-serif",
  fontFamilyMonospace: "'JetBrains Mono', monospace",
  primaryColor: 'blue',
  defaultRadius: 'sm',
  cursorType: 'pointer',
  headings: { fontFamily: "'IBM Plex Sans', sans-serif" },
  components: {
    Badge: { defaultProps: { radius: 'sm', size: 'xs' } },
    TextInput: { defaultProps: { radius: 'sm', size: 'xs' } },
    ScrollArea: { defaultProps: { type: 'hover', scrollbarSize: 6 } },
    SegmentedControl: { defaultProps: { size: 'xs', radius: 'sm' } },
  },
})
