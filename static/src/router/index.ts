import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from '@/api/client'
import AdminLayout from '@/layouts/AdminLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/Login.vue'),
      meta: { title: '登录', public: true },
    },
    {
      path: '/',
      component: AdminLayout,
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('@/views/Dashboard.vue'),
          meta: { title: '概览' },
        },
        {
          path: 'tasks',
          name: 'TaskList',
          component: () => import('@/views/TaskList.vue'),
          meta: { title: '任务列表' },
        },
        {
          path: 'tasks/:id',
          name: 'TaskDetail',
          component: () => import('@/views/TaskDetail.vue'),
          meta: { title: '任务详情' },
          props: true,
        },
        {
          path: 'upload',
          name: 'Upload',
          component: () => import('@/views/Upload.vue'),
          meta: { title: '上传' },
        },
        {
          path: 'process',
          name: 'ProcessDocuments',
          component: () => import('@/views/ProcessDocuments.vue'),
          meta: { title: '处理文档' },
        },
        {
          path: 'download',
          name: 'Download',
          component: () => import('@/views/Download.vue'),
          meta: { title: '下载中心' },
        },
        {
          path: 'templates',
          name: 'Templates',
          component: () => import('@/views/Templates.vue'),
          meta: { title: '模板管理' },
        },
        {
          path: 'evidence',
          name: 'Evidence',
          component: () => import('@/views/EvidencePage.vue'),
          meta: { title: '证据整理' },
        },
        {
          path: 'usage',
          name: 'Usage',
          component: () => import('@/views/UsageView.vue'),
          meta: { title: '用量' },
        },
        {
          path: 'admin',
          name: 'Admin',
          component: () => import('@/views/Admin.vue'),
          meta: { title: '管理后台', requiresAdmin: true },
        },
        {
          path: 'profile',
          name: 'Profile',
          component: () => import('@/views/Profile.vue'),
          meta: { title: '个人中心' },
        },
      ],
    },
  ],
})

// ─── 路由守卫：认证检查 ───
// 每次全新打开页面（新标签页/刷新/输入URL）都必须先经过登录页
let isFirstLoad = true

router.beforeEach((to, _from, next) => {
  const isPublic = to.meta.public === true

  // 首次加载：不管去哪个路由，都先重定向到登录页
  // 后续 SPA 内部导航不受此限制
  if (isFirstLoad && !isPublic) {
    isFirstLoad = false
    next({ name: 'Login' })
    return
  }
  isFirstLoad = false

  if (isPublic) {
    next()
    return
  }

  // 非公开路由：检查是否登录
  if (!isLoggedIn()) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  next()
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'ScanStruct'
  document.title = `${title} — ScanStruct Admin`
})

export default router
