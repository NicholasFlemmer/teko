export interface Coach {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  phone_number: string;
  dob?: string;
  profile_picture?: string | null;
  emergency_name?: string;
  emergency_relationship?: string;
  emergency_phone?: string;
  joined_date?: string;
  notes?: string;
  created_at?: any;
}

export interface Session {
  id: string;
  date: string;
  start_time: string;
  end_time: string;
  coach_id: string;
  coach_ids?: string[];
  team_id?: string;
  location_id?: string;
  location?: { latitude: number; longitude: number };
  address: string;
  status: 'scheduled' | 'reminded' | 'checked_in' | 'missed' | 'completed' | 'cancelled';
  type?: 'practice' | 'match';
  notes?: string;
  check_in_time?: any;
  check_in_location?: { latitude: number; longitude: number };
  location_verified?: boolean;
  distance?: number;
  coach_check_ins?: Record<string, { check_in_time: any; location_verified: boolean; distance?: number }>;
  completed_at?: any;
  cancelled_at?: string;
  cancellation_reason?: string;
  end_prompt_sent?: boolean;
  created_at?: any;
}

export interface Team {
  id: string;
  name: string;
  age_group: string;
  location_id?: string;
  coach_ids?: string[];
  created_at?: any;
}

export interface Player {
  id: string;
  player_id: string;
  first_name: string;
  last_name: string;
  date_of_birth?: string;
  guardian_name?: string;
  guardian_email?: string;
  guardian_primary_phone?: string;
  guardian_secondary_phone?: string;
  special_notes?: string;
  team_ids?: string[];
  created_at?: any;
}

export interface Location {
  id: string;
  name: string;
  address: string;
  google_maps_link?: string;
  radius?: string;
  notes?: string;
  created_at?: any;
}

export interface Broadcast {
  id: string;
  channel: 'whatsapp' | 'email';
  subject: string;
  message: string;
  recipient_ids: string[];
  recipient_count: number;
  status: 'sent' | 'pending' | 'failed';
  cost?: number;
  created_at?: any;
}

export interface ContentItem {
  id: string;
  title: string;
  type: string;
  topic: string;
  language: string;
  content_text?: string;
  file_name?: string;
  created_at?: any;
}

export interface UrlResource {
  id: string;
  url: string;
  title: string;
  description?: string;
  instructions?: string;
  created_at?: any;
}

export interface ReminderConfig {
  id: string;
  type: 'check-in' | 'roll-call' | 'feedback';
  timing: '10min' | '30min' | '1hr' | 'post-session';
  enabled: boolean;
  description: string;
  created_at?: any;
}

export interface Admin {
  id: string;
  name: string;
  email: string;
  role: 'super_admin' | 'admin' | 'manager';
  status: 'active' | 'suspended';
  last_login?: string;
  created_at?: any;
}

export interface Settings {
  maintenance_mode: boolean;
  auto_backup: boolean;
  sender_email: string;
  sender_name: string;
}

export interface ReportStats {
  total_sessions: number;
  check_in_rate: number;
  total_students: number;
  active_coaches: number;
}

export interface ApiResponse<T> {
  success: boolean;
  error?: string;
  [key: string]: any;
}
