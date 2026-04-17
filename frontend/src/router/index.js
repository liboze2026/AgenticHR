import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/resumes', name: 'Resumes', component: () => import('../views/Resumes.vue') },
  { path: '/jobs', name: 'Jobs', component: () => import('../views/Jobs.vue') },
  { path: '/interviewers', name: 'Interviewers', component: () => import('../views/Interviewers.vue') },
  { path: '/interviews', name: 'Interviews', component: () => import('../views/Interviews.vue') },
  { path: '/notifications', name: 'Notifications', component: () => import('../views/Notifications.vue') },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳转登录页
router.beforeEach((to, from, next) => {
  if (to.meta.public) return next()
  const token = localStorage.getItem('token')
  if (!token) return next('/login')
  next()
})

export default router
