# 02 · Vue3 前端：AI 时代仍必须掌握的核心

## 1. 为什么 AI 时代还要认真学 Vue？

AI 能帮你写页面，但不能替代你做三件事：

1. **判断交互是否合理**：表单校验、权限菜单、异步状态，AI 需要你给出准确约束。
2. **调试运行时问题**：响应式不更新、路由守卫、SSE 流式渲染，这些靠原理而不是记忆。
3. **审查生成代码**：大模型写出的 Vue 代码经常混用 Options/Composition API，或漏了响应式。

所以前端要学的不是“背 API”，而是**数据如何驱动视图**。

## 2. Vue3 的核心：响应式

### 2.1 什么是响应式？

```js
const count = ref(0)
// 模板里用 {{ count }}，当 count.value 改变时，视图自动更新。
```

`ref` 和 `reactive` 都是响应式容器，区别是：

- `ref`：适合基本类型，读写要 `.value`；模板里自动解包。
- `reactive`：适合对象，直接改属性；但解构、重新赋值可能丢失响应式。

本项目 AIChat.vue 里有一个很典型的坑：

```js
const assistant = reactive({ role: 'assistant', content: '', steps: [] })
messages.value.push(assistant)
// 之后 assistant.content += token，视图才会实时更新。
```

如果写成普通对象再 push，接口明明有数据，页面却不刷新。
这是新手最常见的“响应式丢失”问题。

### 2.2 计算属性和侦听器

```js
const roleLabel = computed(() => form.role === 'admin' ? '管理员' : '学生')
```

计算属性有缓存，依赖不变就不重新计算。侦听器用于“数据变化后执行副作用”，
例如查询条件变化后重新请求接口。

## 3. Composition API 的骨架

Vue3 推荐 `<script setup>`。一个页面通常长这样：

```vue
<script setup>
import { onMounted, reactive, ref } from 'vue'
import { xxxApi } from '@/api/xxx'

const loading = ref(false)          // 加载状态
const tableData = ref([])           // 表格数据
const params = reactive({ page: 1 }) // 查询参数

const load = async () => {
  loading.value = true
  try {
    const res = await xxxApi(params)
    tableData.value = res.data.list
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
```

这套骨架可以套用几乎所有后台页面：**状态 -> 请求 -> 渲染 -> 交互**。

## 4. 组件通信

### 4.1 父传子：props

`ReserveDialog.vue` 接收实验室/设备信息：

```js
const props = defineProps({
  visible: Boolean,
  labId: Number,
  labName: String
})
```

父组件这样传：

```vue
<ReserveDialog :lab-id="currentLab?.id" :lab-name="currentLab?.name" />
```

### 4.2 子传父：emits

子组件不能改 props，关闭弹窗时通过事件通知父组件：

```js
const emit = defineEmits(['update:visible'])
emit('update:visible', false)
```

配合 `v-model:visible`，实现双向绑定。

## 5. 路由和路由守卫

`router/index.js` 的守卫决定谁能进哪些页面：

```js
router.beforeEach((to) => {
  const token = getToken()
  if (!to.meta.public && !token) return { path: '/login' }
  return true
})
```

菜单权限在前端只做展示控制，真正的安全在后端接口鉴权。
前端隐藏按钮只是体验优化，不能当成安全边界。

## 6. axios 统一封装

`utils/request.js` 做了三件事：

1. 请求拦截器自动加 `Authorization`。
2. 响应拦截器统一判断 `code`，成功返回 data 部分。
3. 401 时清除登录态并跳回登录页。

这让你在页面里只写业务成功逻辑，不用每个接口重复判断错误。

## 7. Vite 与开发代理

`vite.config.js` 把 `/api` 和 `/uploads` 代理到 FastAPI，解决跨域：

```js
proxy: {
  '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true }
}
```

开发环境前端 5173 端口，后端 8000 端口，浏览器请求仍发到 5173，
由 Vite 转给后端，避免 CORS 问题。

## 8. AI 时代要额外掌握的前端知识

- **TypeScript**：大模型生成的代码越来越多，类型能大幅减少运行时错误。
- **状态管理**：Pinia 比 localStorage 更适合复杂共享状态。
- **SSE / WebSocket**：AI 应用大量使用流式输出，本项目就是 SSE。
- **组件设计**：会拆组件，AI 才能高质量地为你扩展功能。
- **无障碍与性能**：AI 能生成代码，但你要负责产品可用性。

## 9. 学习检查清单

完成本项目后，你应该能回答：

- 为什么 `reactive` 对象 push 后再改字段会不更新？
- axios 拦截器解决什么问题？
- 前端路由守卫和后端鉴权分别保护什么？
- 一个后台 CRUD 页面由哪几部分组成？
