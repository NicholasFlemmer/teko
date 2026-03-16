const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5002';
const REQUEST_TIMEOUT_MS = 30_000; // 30 second timeout

let isRedirectingTo401 = false;

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

  // Add timeout via AbortController
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (err: any) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new Error('Request timed out');
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }

  if (response.status === 401) {
    removeToken();
    // Prevent multiple concurrent 401s from racing to redirect
    if (!isRedirectingTo401) {
      isRedirectingTo401 = true;
      window.location.href = '/login';
    }
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
      isRedirectingTo401 = false; // Reset so future 401s can redirect
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
  update: (id: string, data: any, scope?: 'single' | 'future' | 'all') => {
    const qs = scope && scope !== 'single' ? `?scope=${scope}` : '';
    return request<{ success: boolean; session?: any; message?: string }>(`/api/sessions/${id}${qs}`, { method: 'PUT', body: JSON.stringify(data) });
  },
  delete: (id: string, scope?: 'single' | 'future' | 'all') => {
    const qs = scope && scope !== 'single' ? `?scope=${scope}` : '';
    return request<{ success: boolean; message?: string }>(`/api/sessions/${id}${qs}`, { method: 'DELETE' });
  },
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
  bulkUpload: async (file: File, teamIds: string[] = []) => {
    const token = getToken();
    const formData = new FormData();
    formData.append('file', file);
    teamIds.forEach(id => formData.append('team_ids', id));

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 120_000);

    let response: Response;
    try {
      response = await fetch(`${API_URL}/api/players/bulk-upload`, {
        method: 'POST',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        body: formData,
        signal: controller.signal,
      });
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') throw new Error('Upload timed out');
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }

    if (response.status === 401) {
      removeToken();
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }

    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Bulk upload failed');
    return data as { success: boolean; created_count: number; error_count: number; errors: { row: number; error: string }[]; message: string };
  },
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
  send: (data: any) => request<{ success: boolean; broadcast: any; estimated_cost?: any }>('/api/broadcasts', { method: 'POST', body: JSON.stringify(data) }),
  getTemplates: () => request<{ success: boolean; templates: any[] }>('/api/broadcasts/templates'),
  getTemplatePreview: (name: string) => request<{ success: boolean; template: any }>(`/api/broadcasts/templates/${name}`),
  estimateCost: (recipientCount: number, messageType: 'marketing' | 'utility' | 'service') =>
    request<{ success: boolean; cost_usd: number; cost_zar: number; recipient_count: number; rate_per_message_usd: number; usd_to_zar_rate: number }>('/api/broadcasts/estimate-cost', {
      method: 'POST',
      body: JSON.stringify({ recipient_count: recipientCount, message_type: messageType }),
    }),
  getPricing: () => request<{ success: boolean; pricing: any }>('/api/broadcasts/pricing'),
  updatePricing: (data: any) => request<{ success: boolean; pricing: any }>('/api/broadcasts/pricing', { method: 'PUT', body: JSON.stringify(data) }),
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

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 120_000); // 2 min upload timeout

    let response: Response;
    try {
      response = await fetch(`${API_URL}/api/uploads`, {
        method: 'POST',
        headers: token ? { 'Authorization': `Bearer ${token}` } : {},
        body: formData,
        signal: controller.signal,
      });
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') throw new Error('Upload timed out');
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }

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

// SSE (Server-Sent Events)
export const sseAPI = {
  /** Subscribe to the coach activity stream. Returns an EventSource; caller must close it. */
  coachActivity: (onEvent: (event: { type: string; coach_name: string; preview: string; timestamp: string }) => void): EventSource | null => {
    const token = getToken();
    if (!token) return null;
    const es = new EventSource(`${API_URL}/api/sse/coach-activity?token=${encodeURIComponent(token)}`);
    es.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data));
      } catch { /* ignore malformed events */ }
    };
    return es;
  },
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
