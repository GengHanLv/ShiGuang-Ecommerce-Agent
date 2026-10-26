<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ProductImage } from '@/types'
import { safeProductImages, productImageUrl } from '@/utils/media'
import { useConnectionStore } from '@/stores/connection'
const connection = useConnectionStore()
function sourceHost(url: string) {
  return new URL(url).hostname
}

const props = defineProps<{ images?: ProductImage[] }>()
const images = computed(() => safeProductImages(props.images))
const failed = ref<Record<string, boolean>>({})
</script>

<template>
  <div
    v-if="images.length"
    class="product-gallery"
    aria-label="相关商品来源图片"
  >
    <figure v-for="item in images" :key="item.url" class="product-card">
      <a
        :href="item.source_url"
        target="_blank"
        rel="noopener noreferrer"
        referrerpolicy="no-referrer"
        :aria-label="`查看 ${item.model} 来源页面`"
        class="product-visual"
      >
        <span v-if="failed[item.url]" class="image-fallback"
          >图片暂时无法显示</span
        >
        <img
          v-else
          :src="productImageUrl(item.url, connection.baseUrl)"
          :alt="item.alt"
          loading="lazy"
          decoding="async"
          referrerpolicy="no-referrer"
          @error="failed[item.url] = true"
        />
      </a>
      <figcaption>
        <strong>{{ item.model }}</strong>
        <a
          :href="item.source_url"
          target="_blank"
          rel="noopener noreferrer"
          referrerpolicy="no-referrer"
          >{{ sourceHost(item.source_url) }} · 查看来源 ↗</a
        >
        <small>来源页面配图；具体版本、颜色及是否实拍以原文为准</small>
      </figcaption>
    </figure>
  </div>
</template>

<style scoped>
.product-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
  gap: 14px;
  margin-top: 20px;
  max-width: 760px;
}
.product-card {
  margin: 0;
  border: 1px solid var(--border, #e6e9ef);
  border-radius: 16px;
  background: #fff;
  overflow: hidden;
  min-width: 0;
}
.product-visual {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f7f8fa;
  height: 180px;
  padding: 16px;
}
.product-visual img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  transition: transform 0.25s ease;
}
.product-visual:hover img {
  transform: scale(1.035);
}
figcaption {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 14px 16px;
}
figcaption strong {
  font-size: 15px;
  color: #273443;
}
figcaption a {
  font-size: 13px;
  color: #327969;
  text-decoration: none;
}
figcaption a:hover {
  text-decoration: underline;
}
figcaption small,
.image-fallback {
  font-size: 12px;
  color: #7b8592;
  line-height: 1.6;
}
@media (prefers-reduced-motion: reduce) {
  .product-visual img {
    transition: none;
  }
}
</style>
