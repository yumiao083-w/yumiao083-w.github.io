<script>
export default {
  onLaunch() {
    console.log('App Launch');
  },
  onShow() {
    console.log('App Show');
  },
  onHide() {
    console.log('App Hide');
  }
};
</script>

<style>
/* 全局样式 —— 不能 scoped，page 元素必须在此设置 */
page {
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  background-color: #000;
  /* 防止页面水平溢出/偏移 */
  width: 100%;
  max-width: 100vw;
  overflow-x: hidden;
  margin: 0;
  padding: 0;
}
/* 确保所有元素 box-sizing 一致 */
view, text, input, textarea, button, scroll-view, image {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}
button::after {
  border: none;
}
/* uni-app 默认会给 page 添加 padding，强制清除 */
uni-page-body {
  overflow-x: hidden;
  width: 100%;
}
</style>
