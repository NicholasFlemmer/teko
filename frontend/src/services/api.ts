import type { Organisation, Terminology } from '@/types/Organisation';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5002';
const REQUEST_TIMEOUT_MS = 30_000; // 30 second timeout

let isRedirectingTo401 = false;

// A 401 from these endpoints is a failed attempt (bad credentials, bad/
// expired token, bad invite), not an expired session -- the caller's own
// error-message mapping needs the real response body, and there is no
// active session to protect by redirecting. Every other endpoint keeps the
// global redirect-on-401 behaviour below, where a 401 does mean "your
// session expired."
const AUTH_ENDPOINTS_EXEMPT_FROM_401_REDIRECT = new Set([
  '/api/auth/login',
  '/api/auth/forgot-password',
  '/api/auth/reset-password',
  '/api/auth/accept-invite',
]);

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

  if (response.status === 401 && !AUTH_ENDPOINTS_EXEMPT_FROM_401_REDIRECT.has(endpoint)) {
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

  forgotPassword: (email: string) =>
    request<{ message: string }>('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),

  resetPassword: (token: string, password: string) =>
    request<{ message: string }>('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, password }),
    }),

  invite: (email: string, role: string) =>
    request<{ message: string }>('/api/auth/invite', {
      method: 'POST',
      body: JSON.stringify({ email, role }),
    }),

  acceptInvite: (token: string, first_name: string, last_name: string, password: string) =>
    request<{ message: string }>('/api/auth/accept-invite', {
      method: 'POST',
      body: JSON.stringify({ token, first_name, last_name, password }),
    }),

  verify: () => request<{ valid: boolean; username: string }>('/api/auth/verify'),

  logout: () => {
    removeToken();
    window.location.href = '/login';
  },

  isAuthenticated: () => !!getToken(),
};

// Organisations
export const organisationsAPI = {
  getAll: () => request<{ success: boolean; organisations: Organisation[] }>('/api/organisations'),
  getById: (orgId: string) =>
    request<{ success: boolean; organisation: Organisation }>(`/api/organisations/${orgId}`),
  update: (
    orgId: string,
    data: Partial<
      Pick<
        Organisation,
        | 'name'
        | 'type'
        | 'terminology'
        | 'safeguarding_lead_name'
        | 'safeguarding_lead_email'
        | 'works_with_minors'
        | 'attendance_mode'
      >
    >
  ) =>
    request<{ success: boolean; organisation: Organisation }>(`/api/organisations/${orgId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  getTerminology: (orgId: string) =>
    request<{ success: boolean; terminology: Terminology }>(`/api/organisations/${orgId}/terminology`),
};

// Admin users (org-scoped)
export const adminsAPI = {
  getAll: () => request<{ success: boolean; admins: any[] }>('/api/admins'),
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
  sendReminder: (id: string) => request<{ success: boolean; results?: any[] }>(`/api/sessions/${id}/send-reminder`, { method: 'POST' }),
  cancel: (id: string, reason?: string) => request<{ success: boolean; session: any }>(`/api/sessions/${id}/cancel`, { method: 'PATCH', body: JSON.stringify({ reason }) }),
  getAttendance: (id: string) => request<{ success: boolean; attended_player_ids: string[] }>(`/api/sessions/${id}/attendance`),
  updateAttendance: (id: string, playerIds: string[]) => request<{ success: boolean; session: any }>(`/api/sessions/${id}/attendance`, { method: 'PUT', body: JSON.stringify({ attended_player_ids: playerIds }) }),
  getPhotos: (id: string) => request<{ success: boolean; photos: any[] }>(`/api/sessions/${id}/photos`),
  addPhoto: (id: string, url: string, file_path?: string) =>
    request<{ success: boolean; photo: any }>(`/api/sessions/${id}/photos`, { method: 'POST', body: JSON.stringify({ url, file_path }) }),
  deletePhoto: (id: string, photoId: string) =>
    request<{ success: boolean }>(`/api/sessions/${id}/photos/${photoId}`, { method: 'DELETE' }),
};

// Public session endpoints used by the coach check-in flow (token-authenticated, no JWT)
export const checkInAPI = {
  uploadPhoto: async (token: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 120_000);
    let response: Response;
    try {
      response = await fetch(`${API_URL}/api/uploads/check-in/${token}`, {
        method: 'POST',
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
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Upload failed');
    return data as { success: boolean; file: { public_url: string; file_path: string } };
  },
  attachPhoto: async (token: string, url: string, file_path?: string) => {
    const res = await fetch(`${API_URL}/api/sessions/check-in/${token}/photos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, file_path }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to attach photo');
    return data as { success: boolean; photo: any };
  },
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
  geocode: (address: string) =>
    request<{ success: boolean; latitude: number; longitude: number }>('/api/locations/geocode', {
      method: 'POST',
      body: JSON.stringify({ address }),
    }),
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
  getSchedulerStatus: () =>
    request<{
      success: boolean;
      reminder_minutes_before: number;
      last_run: {
        reminders: { ran_at?: string; reminders_sent?: number; errors?: string[]; success?: boolean; error?: string } | null;
        end_prompts: { ran_at?: string; prompts_sent?: number; errors?: string[]; success?: boolean; error?: string } | null;
        missed: { ran_at?: string; sessions_marked_missed?: number; success?: boolean; error?: string } | null;
      };
    }>('/api/admin/scheduler/status'),
  runReminders: () =>
    request<{ success: boolean; result: { reminders_sent: number; errors: string[] } }>('/api/admin/scheduler/run-reminders', { method: 'POST' }),
};
