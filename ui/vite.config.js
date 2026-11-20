import {defineConfig} from 'vite';

export default defineConfig({
  build: {
    assetsInlineLimit: 1000000,
    cssCodeSplit: false,
    rollupOptions: {output: {entryFileNames: 'app.js', assetFileNames: 'app.[ext]', inlineDynamicImports: true}},
  },
});
