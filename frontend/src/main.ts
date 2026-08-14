import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import ElementPlusX from 'vue-element-plus-x'

import App from './App.vue'
import 'element-plus/dist/index.css'
import 'vue-element-plus-x/styles/index.css'
import './styles.css'

createApp(App).use(ElementPlus).use(ElementPlusX).mount('#app')
