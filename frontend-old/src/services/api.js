import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';

// Create axios instance
const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle errors
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Just log the error instead of redirecting
    if (error.response?.status === 401) {
      console.warn('Authentication error - continuing without auth');
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authAPI = {
  login: (username, password) =>
    api.post('/api/auth/login', { username, password }),
  verify: () => api.get('/api/auth/verify'),
};

// Coaches API
export const coachesAPI = {
  getAll: () => api.get('/api/coaches'),
  getOne: (id) => api.get(`/api/coaches/${id}`),
  create: (data) => api.post('/api/coaches', data),
  update: (id, data) => api.put(`/api/coaches/${id}`, data),
  delete: (id) => api.delete(`/api/coaches/${id}`),
};

// Sessions API
export const sessionsAPI = {
  getAll: (params) => api.get('/api/sessions', { params }),
  getOne: (id) => api.get(`/api/sessions/${id}`),
  create: (data) => api.post('/api/sessions', data),
  update: (id, data) => api.put(`/api/sessions/${id}`, data),
  delete: (id) => api.delete(`/api/sessions/${id}`),
  sendReminder: (id) => api.post(`/api/sessions/${id}/send-reminder`),
};

// Check-in API (public endpoints)
export const checkInAPI = {
  getInfo: (token) => axios.get(`${API_URL}/api/sessions/check-in/${token}`),
  checkIn: (token, location) =>
    axios.post(`${API_URL}/api/sessions/check-in/${token}`, { location }),
};

export default api;
