const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5002';

function getToken(): string | null {
  return localStorage.getItem('token');
}

function setToken(token: string): void {
  localStorage.setItem('token', token);
}

function removeToken(): void {
  localStorage.removeItem('token');
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    removeToken();
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  let data: any;
  try {
    data = await response.json();
  } catch {
    throw new Error(`Server error (${response.status})`);
  }

  if (!response.ok) {
    throw new Error(data.error || 'Request failed');
  }

  return data;
}

// Auth
export const authAPI = {
  login: (email: string, password: string) =>
    request<{ token: string; username: string; expires_in: number }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: email, password }),
    }).then(data => {
      setToken(data.token);
      return data;
    }),

  verify: () => request<{ valid: boolean; username: string }>('/api/auth/verify'),

  logout: () => {
    removeToken();
    window.location.href = '/login';
  },

  isAuthenticated: () => !!getToken(),
};

// Coaches
export const coachesAPI = {
  getAll: () => request<{ success: boolean; coaches: any[] }>('/api/coaches'),
  getOne: (id: string) => request<{ success: boolean; coach: any }>(`/api/coaches/${id}`),
  create: (data: any) => request<{ success: boolean; coach: any }>('/api/coaches', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => request<{ success: boolean; coach: any }>(`/api/coaches/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ success: boolean }>(`/api/coaches/${id}`, { method: 'DELETE' }),
};

// Sessions
export const sessionsAPI = {
  getAll: (params?: { start_date?: string; end_date?: string; coach_id?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.start_date) searchParams.set('start_date', params.start_date);
    if (params?.end_date) searchParams.set('end_date', params.end_date);
    if (params?.coach_id) searchParams.set('coach_id', params.coach_id);
    const qs = searchParams.toString();
    return request<{ success: boolean; sessions: any[] }>(`/api/sessions${qs ? `?${qs}` : ''}`);
  },
  getOne: (id: string) => request<{ success: boolean; session: any }>(`/api/sessions/${id}`),
  create: (data: any) => request<{ success: boolean; session: any }>('/api/sessions', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => request<{ success: boolean; session: any }>(`/api/sessions/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ success: boolean }>(`/api/sessions/${id}`, { method: 'DELETE' }),
  sendReminder: (id: string) => request<{ success: boolean }>(`/api/sessions/${id}/send-reminder`, { method: 'POST' }),
  getAttendance: (id: string) => request<{ success: boolean; attended_player_ids: string[] }>(`/api/sessions/${id}/attendance`),
  updateAttendance: (id: string, playerIds: string[]) => request<{ success: boolean; session: any }>(`/api/sessions/${id}/attendance`, { method: 'PUT', body: JSON.stringify({ attended_player_ids: playerIds }) }),
};

// Teams
export const teamsAPI = {
  getAll: (params?: { location_id?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.location_id) searchParams.set('location_id', params.location_id);
    const qs = searchParams.toString();
    return request<{ success: boolean; teams: any[] }>(`/api/teams${qs ? `?${qs}` : ''}`);
  },
  getOne: (id: string) => request<{ success: boolean; team: any }>(`/api/teams/${id}`),
  create: (data: any) => request<{ success: boolean; team: any }>('/api/teams', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => request<{ success: boolean; team: any }>(`/api/teams/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ success: boolean }>(`/api/teams/${id}`, { method: 'DELETE' }),
};

// Players
export const playersAPI = {
  getAll: (params?: { team_id?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.team_id) searchParams.set('team_id', params.team_id);
    const qs = searchParams.toString();
    return request<{ success: boolean; players: any[] }>(`/api/players${qs ? `?${qs}` : ''}`);
  },
  getOne: (id: string) => request<{ success: boolean; player: any }>(`/api/players/${id}`),
  create: (data: any) => request<{ success: boolean; player: any }>('/api/players', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => request<{ success: boolean; player: any }>(`/api/players/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ success: boolean }>(`/api/players/${id}`, { method: 'DELETE' }),
};

// Locations
export const locationsAPI = {
  getAll: () => request<{ success: boolean; locations: any[] }>('/api/locations'),
  getOne: (id: string) => request<{ success: boolean; location: any }>(`/api/locations/${id}`),
  create: (data: any) => request<{ success: boolean; location: any }>('/api/locations', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => request<{ success: boolean; location: any }>(`/api/locations/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ success: boolean }>(`/api/locations/${id}`, { method: 'DELETE' }),
};

// Broadcasts
export const broadcastsAPI = {
  getAll: () => request<{ success: boolean; broadcasts: any[] }>('/api/broadcasts'),
  send: (data: any) => request<{ success: boolean; broadcast: any }>('/api/broadcasts', { method: 'POST', body: JSON.stringify(data) }),
  getTemplates: () => request<{ success: boolean; templates: any[] }>('/api/broadcasts/templates'),
};

// Content
export const contentAPI = {
  getAll: () => request<{ success: boolean; content: any[] }>('/api/content'),
  create: (data: any) => request<{ success: boolean; content: any }>('/api/content', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => request<{ success: boolean; content: any }>(`/api/content/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ success: boolean }>(`/api/content/${id}`, { method: 'DELETE' }),
  // URL resources
  getAllUrls: () => request<{ success: boolean; urls: any[] }>('/api/content/urls'),
  createUrl: (data: any) => request<{ success: boolean; url: any }>('/api/content/urls', { method: 'POST', body: JSON.stringify(data) }),
  updateUrl: (id: string, data: any) => request<{ success: boolean; url: any }>(`/api/content/urls/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteUrl: (id: string) => request<{ success: boolean }>(`/api/content/urls/${id}`, { method: 'DELETE' }),
};

// Reports
export const reportsAPI = {
  getCoachAttendance: (params?: { start_date?: string; end_date?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.start_date) searchParams.set('start_date', params.start_date);
    if (params?.end_date) searchParams.set('end_date', params.end_date);
    const qs = searchParams.toString();
    return request<{ success: boolean; data: any[] }>(`/api/reports/coach-attendance${qs ? `?${qs}` : ''}`);
  },
  getLocationAttendance: (params?: { start_date?: string; end_date?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.start_date) searchParams.set('start_date', params.start_date);
    if (params?.end_date) searchParams.set('end_date', params.end_date);
    const qs = searchParams.toString();
    return request<{ success: boolean; data: any[] }>(`/api/reports/location-attendance${qs ? `?${qs}` : ''}`);
  },
  getStudentRollcall: (params?: { start_date?: string; end_date?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.start_date) searchParams.set('start_date', params.start_date);
    if (params?.end_date) searchParams.set('end_date', params.end_date);
    const qs = searchParams.toString();
    return request<{ success: boolean; data: any[] }>(`/api/reports/student-rollcall${qs ? `?${qs}` : ''}`);
  },
  getStats: () => request<{ success: boolean; stats: any }>('/api/reports/stats'),
};

// Reminders
export const remindersAPI = {
  getAll: () => request<{ success: boolean; reminders: any[] }>('/api/reminders'),
  create: (data: any) => request<{ success: boolean; reminder: any }>('/api/reminders', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: any) => request<{ success: boolean; reminder: any }>(`/api/reminders/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ success: boolean }>(`/api/reminders/${id}`, { method: 'DELETE' }),
};

// Uploads
export const uploadsAPI = {
  upload: async (file: File, folder: string = 'uploads') => {
    const token = getToken();
    const formData = new FormData();
    formData.append('file', file);
    formData.append('folder', folder);

    const response = await fetch(`${API_URL}/api/uploads`, {
      method: 'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      body: formData,
    });

    if (response.status === 401) {
      removeToken();
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }

    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Upload failed');
    return data as { success: boolean; file: { file_name: string; file_path: string; public_url: string; content_type: string; size: number } };
  },
  delete: (filePath: string) => request<{ success: boolean }>(`/api/uploads/${filePath}`, { method: 'DELETE' }),
};

// Admin
export const adminAPI = {
  getUsers: () => request<{ success: boolean; admins: any[] }>('/api/admin/users'),
  createUser: (data: any) => request<{ success: boolean; admin: any }>('/api/admin/users', { method: 'POST', body: JSON.stringify(data) }),
  updateUser: (id: string, data: any) => request<{ success: boolean; admin: any }>(`/api/admin/users/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteUser: (id: string) => request<{ success: boolean }>(`/api/admin/users/${id}`, { method: 'DELETE' }),
  toggleStatus: (id: string) => request<{ success: boolean; admin: any }>(`/api/admin/users/${id}/toggle-status`, { method: 'PUT' }),
  getSettings: () => request<{ success: boolean; settings: any }>('/api/admin/settings'),
  updateSettings: (data: any) => request<{ success: boolean; settings: any }>('/api/admin/settings', { method: 'PUT', body: JSON.stringify(data) }),
};
