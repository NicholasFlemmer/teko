import React, { useState, useEffect } from 'react';
import { Calendar, momentLocalizer } from 'react-big-calendar';
import moment from 'moment';
import { sessionsAPI, coachesAPI } from '../services/api';
import LocationAutocomplete from '../components/LocationAutocomplete';
import Toast from '../components/Toast';
import ConfirmDialog from '../components/ConfirmDialog';
import { useTheme } from '../contexts/ThemeContext';
import 'react-big-calendar/lib/css/react-big-calendar.css';

const localizer = momentLocalizer(moment);

// Skeleton Loading Components
const StatCardSkeleton = () => (
  <div className="stat-card animate-pulse">
    <div className="flex items-center justify-between">
      <div className="space-y-2">
        <div className="h-4 w-20 bg-gray-200 dark:bg-gray-700 rounded"></div>
        <div className="h-8 w-12 bg-gray-200 dark:bg-gray-700 rounded"></div>
      </div>
      <div className="w-14 h-14 bg-gray-200 dark:bg-gray-700 rounded-2xl"></div>
    </div>
  </div>
);

const CalendarSkeleton = () => (
  <div className="glass-card p-6 animate-pulse">
    <div className="flex justify-between mb-6">
      <div className="flex gap-2">
        <div className="h-10 w-20 bg-gray-200 dark:bg-gray-700 rounded-lg"></div>
        <div className="h-10 w-20 bg-gray-200 dark:bg-gray-700 rounded-lg"></div>
      </div>
      <div className="h-10 w-40 bg-gray-200 dark:bg-gray-700 rounded-lg"></div>
      <div className="flex gap-2">
        <div className="h-10 w-24 bg-gray-200 dark:bg-gray-700 rounded-lg"></div>
        <div className="h-10 w-24 bg-gray-200 dark:bg-gray-700 rounded-lg"></div>
      </div>
    </div>
    <div className="grid grid-cols-7 gap-2">
      {[...Array(35)].map((_, i) => (
        <div key={i} className="h-24 bg-gray-100 dark:bg-gray-700/50 rounded-lg"></div>
      ))}
    </div>
  </div>
);

// Progress Ring Component
const ProgressRing = ({ progress, size = 56, strokeWidth = 4, color }) => {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (progress / 100) * circumference;

  return (
    <svg width={size} height={size} className="transform -rotate-90">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        className="text-gray-200 dark:text-gray-700"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        className="transition-all duration-700 ease-out"
      />
    </svg>
  );
};

function Dashboard() {
  const { darkMode } = useTheme();
  const [coaches, setCoaches] = useState([]);
  const [events, setEvents] = useState([]);
  const [allSessions, setAllSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterCoach, setFilterCoach] = useState('all');
  const [toast, setToast] = useState(null);
  const [confirmDialog, setConfirmDialog] = useState({ isOpen: false });
  const [showMoreEvents, setShowMoreEvents] = useState(null);

  const [newSession, setNewSession] = useState({
    date: '',
    start_time: '',
    end_time: '',
    coach_id: '',
    address: '',
    latitude: '',
    longitude: '',
  });

  const [editSession, setEditSession] = useState(null);

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    filterAndSetEvents();
  }, [allSessions, filterStatus, filterCoach, coaches]);

  const loadData = async () => {
    try {
      const [sessionsRes, coachesRes] = await Promise.all([
        sessionsAPI.getAll(),
        coachesAPI.getAll(),
      ]);

      setCoaches(coachesRes.data.coaches);
      setAllSessions(sessionsRes.data.sessions);
    } catch (error) {
      showToast('Error loading data: ' + error.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const filterAndSetEvents = () => {
    let filtered = [...allSessions];

    if (filterStatus !== 'all') {
      filtered = filtered.filter((s) => s.status === filterStatus);
    }

    if (filterCoach !== 'all') {
      filtered = filtered.filter((s) => s.coach_id === filterCoach);
    }

    const calendarEvents = filtered.map((session) => {
      const coach = coaches.find((c) => c.id === session.coach_id);
      const startDateTime = new Date(`${session.date}T${session.start_time}`);
      const endDateTime = new Date(`${session.date}T${session.end_time}`);

      return {
        id: session.id,
        title: `${coach?.name || 'Unknown'} - ${session.address}`,
        start: startDateTime,
        end: endDateTime,
        resource: session,
      };
    });

    setEvents(calendarEvents);
  };

  const showToast = (message, type = 'success') => {
    setToast({ message, type });
  };

  const handleSelectEvent = (event) => {
    setSelectedSession(event.resource);
    setShowModal(true);
  };

  const handleShowMore = (events) => {
    setShowMoreEvents(events);
  };

  const handleCreateSession = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await sessionsAPI.create({
        ...newSession,
        location: {
          latitude: parseFloat(newSession.latitude),
          longitude: parseFloat(newSession.longitude),
        },
      });
      setShowCreateModal(false);
      setNewSession({
        date: '',
        start_time: '',
        end_time: '',
        coach_id: '',
        address: '',
        latitude: '',
        longitude: '',
      });
      await loadData();
      showToast('Session created successfully!');
    } catch (error) {
      showToast('Error creating session: ' + (error.response?.data?.error || error.message), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleEditSession = async (e) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await sessionsAPI.update(editSession.id, {
        ...editSession,
        location: {
          latitude: parseFloat(editSession.latitude),
          longitude: parseFloat(editSession.longitude),
        },
      });
      setShowEditModal(false);
      setEditSession(null);
      await loadData();
      showToast('Session updated successfully!');
    } catch (error) {
      showToast('Error updating session: ' + (error.response?.data?.error || error.message), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteSession = (session) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Delete Session',
      message: `Are you sure you want to delete this session? This action cannot be undone.`,
      confirmText: 'Delete',
      type: 'danger',
      onConfirm: async () => {
        setActionLoading(true);
        try {
          await sessionsAPI.delete(session.id);
          setConfirmDialog({ isOpen: false });
          setShowModal(false);
          await loadData();
          showToast('Session deleted successfully!');
        } catch (error) {
          showToast('Error deleting session: ' + (error.response?.data?.error || error.message), 'error');
        } finally {
          setActionLoading(false);
        }
      },
      onClose: () => setConfirmDialog({ isOpen: false }),
    });
  };

  const handleSendReminder = async () => {
    if (!selectedSession) return;
    setActionLoading(true);
    try {
      await sessionsAPI.sendReminder(selectedSession.id);
      showToast('Reminder sent successfully!');
      setShowModal(false);
      await loadData();
    } catch (error) {
      showToast('Error sending reminder: ' + (error.response?.data?.error || error.message), 'error');
    } finally {
      setActionLoading(false);
    }
  };

  const openEditModal = (session) => {
    setEditSession({
      ...session,
      latitude: session.location?.latitude || '',
      longitude: session.location?.longitude || '',
    });
    setShowEditModal(true);
    setShowModal(false);
  };

  const eventStyleGetter = (event) => {
    const session = event.resource;
    const colorMap = {
      checked_in: '#10b981',
      missed: '#ef4444',
      reminded: '#f59e0b',
      scheduled: '#3b82f6',
    };

    return {
      style: {
        backgroundColor: colorMap[session.status] || colorMap.scheduled,
        borderRadius: '8px',
        opacity: 0.95,
        color: 'white',
        border: '0px',
        display: 'block',
        fontWeight: '500',
      },
    };
  };

  const stats = {
    total: allSessions.length,
    scheduled: allSessions.filter((s) => s.status === 'scheduled').length,
    reminded: allSessions.filter((s) => s.status === 'reminded').length,
    checked_in: allSessions.filter((s) => s.status === 'checked_in').length,
    missed: allSessions.filter((s) => s.status === 'missed').length,
  };

  const getUpcomingSessions = () => {
    const now = new Date();
    return allSessions
      .filter((s) => {
        const sessionDate = new Date(`${s.date}T${s.start_time}`);
        return sessionDate >= now && s.status !== 'checked_in' && s.status !== 'missed';
      })
      .sort((a, b) => new Date(`${a.date}T${a.start_time}`) - new Date(`${b.date}T${b.start_time}`))
      .slice(0, 5);
  };

  const StatusBadge = ({ status }) => {
    const badges = {
      scheduled: 'badge-blue',
      reminded: 'badge-yellow',
      checked_in: 'badge-green',
      missed: 'badge-red',
    };

    const labels = {
      scheduled: 'Scheduled',
      reminded: 'Reminded',
      checked_in: 'Checked In',
      missed: 'Missed',
    };

    return (
      <span className={`badge ${badges[status] || badges.scheduled}`}>
        {labels[status] || status}
      </span>
    );
  };

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        {/* Stats Skeleton */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          {[...Array(5)].map((_, i) => (
            <StatCardSkeleton key={i} />
          ))}
        </div>
        {/* Calendar Skeleton */}
        <CalendarSkeleton />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Toast Notifications */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmDialog} />

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl lg:text-3xl font-bold text-gray-900 dark:text-white">
            Dashboard
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Manage your coaching sessions
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="btn-primary flex items-center gap-2 self-start"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Session
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Total */}
        <div className="stat-card group">
          <div className="absolute inset-0 bg-gradient-to-br from-gray-500/5 to-gray-600/5 rounded-2xl"></div>
          <div className="relative flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Total</p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white mt-1">{stats.total}</p>
            </div>
            <div className="relative">
              <div className="w-14 h-14 bg-gray-100 dark:bg-gray-700 rounded-2xl flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
                <svg className="w-7 h-7 text-gray-600 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
              </div>
            </div>
          </div>
        </div>

        {/* Scheduled */}
        <div className="stat-card group">
          <div className="absolute inset-0 bg-gradient-to-br from-blue-500/5 to-indigo-500/5 rounded-2xl"></div>
          <div className="relative flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-blue-600 dark:text-blue-400">Scheduled</p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white mt-1">{stats.scheduled}</p>
            </div>
            <div className="relative flex items-center justify-center">
              <ProgressRing
                progress={stats.total > 0 ? (stats.scheduled / stats.total) * 100 : 0}
                color="#3b82f6"
              />
              <svg className="w-6 h-6 text-blue-600 absolute" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
        </div>

        {/* Reminded */}
        <div className="stat-card group">
          <div className="absolute inset-0 bg-gradient-to-br from-yellow-500/5 to-orange-500/5 rounded-2xl"></div>
          <div className="relative flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-yellow-600 dark:text-yellow-400">Reminded</p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white mt-1">{stats.reminded}</p>
            </div>
            <div className="relative flex items-center justify-center">
              <ProgressRing
                progress={stats.total > 0 ? (stats.reminded / stats.total) * 100 : 0}
                color="#f59e0b"
              />
              <svg className="w-6 h-6 text-yellow-600 absolute" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
            </div>
          </div>
        </div>

        {/* Checked In */}
        <div className="stat-card group">
          <div className="absolute inset-0 bg-gradient-to-br from-green-500/5 to-emerald-500/5 rounded-2xl"></div>
          <div className="relative flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-green-600 dark:text-green-400">Checked In</p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white mt-1">{stats.checked_in}</p>
            </div>
            <div className="relative flex items-center justify-center">
              <ProgressRing
                progress={stats.total > 0 ? (stats.checked_in / stats.total) * 100 : 0}
                color="#10b981"
              />
              <svg className="w-6 h-6 text-green-600 absolute" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
        </div>

        {/* Missed */}
        <div className="stat-card group">
          <div className="absolute inset-0 bg-gradient-to-br from-red-500/5 to-rose-500/5 rounded-2xl"></div>
          <div className="relative flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-red-600 dark:text-red-400">Missed</p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white mt-1">{stats.missed}</p>
            </div>
            <div className="relative flex items-center justify-center">
              <ProgressRing
                progress={stats.total > 0 ? (stats.missed / stats.total) * 100 : 0}
                color="#ef4444"
              />
              <svg className="w-6 h-6 text-red-600 absolute" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        {/* Calendar Section */}
        <div className="xl:col-span-3 space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap gap-3">
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="select-field w-auto min-w-[150px]"
            >
              <option value="all">All Statuses</option>
              <option value="scheduled">Scheduled</option>
              <option value="reminded">Reminded</option>
              <option value="checked_in">Checked In</option>
              <option value="missed">Missed</option>
            </select>

            <select
              value={filterCoach}
              onChange={(e) => setFilterCoach(e.target.value)}
              className="select-field w-auto min-w-[150px]"
            >
              <option value="all">All Coaches</option>
              {coaches.map((coach) => (
                <option key={coach.id} value={coach.id}>
                  {coach.name}
                </option>
              ))}
            </select>
          </div>

          {/* Calendar */}
          <div className="glass-card p-4 lg:p-6">
            <Calendar
              localizer={localizer}
              events={events}
              startAccessor="start"
              endAccessor="end"
              style={{ height: 600 }}
              onSelectEvent={handleSelectEvent}
              onShowMore={handleShowMore}
              eventPropGetter={eventStyleGetter}
              views={['month', 'week', 'day']}
              defaultView="month"
              min={new Date(0, 0, 0, 6, 0, 0)}
              max={new Date(0, 0, 0, 23, 0, 0)}
            />
          </div>

          {/* Legend */}
          <div className="glass-card p-4">
            <div className="flex flex-wrap items-center gap-6">
              <span className="text-sm font-medium text-gray-600 dark:text-gray-300">Legend:</span>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-blue-500"></span>
                <span className="text-sm text-gray-600 dark:text-gray-300">Scheduled</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-yellow-500"></span>
                <span className="text-sm text-gray-600 dark:text-gray-300">Reminded</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-green-500"></span>
                <span className="text-sm text-gray-600 dark:text-gray-300">Checked In</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-red-500"></span>
                <span className="text-sm text-gray-600 dark:text-gray-300">Missed</span>
              </div>
            </div>
          </div>
        </div>

        {/* Sidebar - Upcoming Sessions */}
        <div className="xl:col-span-1">
          <div className="glass-card p-5 sticky top-4">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-lg flex items-center justify-center">
                <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h3 className="font-semibold text-gray-900 dark:text-white">Upcoming</h3>
            </div>

            <div className="space-y-3">
              {getUpcomingSessions().length === 0 ? (
                <div className="text-center py-8">
                  <div className="w-12 h-12 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center mx-auto mb-3">
                    <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400">No upcoming sessions</p>
                </div>
              ) : (
                getUpcomingSessions().map((session, index) => {
                  const coach = coaches.find((c) => c.id === session.coach_id);
                  return (
                    <div
                      key={session.id}
                      onClick={() => {
                        setSelectedSession(session);
                        setShowModal(true);
                      }}
                      className={`p-3 rounded-xl border cursor-pointer transition-all duration-200 hover:scale-[1.02] ${
                        darkMode
                          ? 'bg-gray-700/50 border-gray-600 hover:bg-gray-700'
                          : 'bg-gray-50 border-gray-100 hover:bg-gray-100'
                      }`}
                      style={{ animationDelay: `${index * 100}ms` }}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-medium text-gray-900 dark:text-white text-sm truncate">
                          {coach?.name || 'Unknown'}
                        </span>
                        <StatusBadge status={session.status} />
                      </div>
                      <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                        {moment(session.date).format('MMM D')} at {session.start_time}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 mt-1 truncate">
                        <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                        <span className="truncate">{session.address}</span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>

      {/* View More Events Modal */}
      {showMoreEvents && (
        <div className="modal-overlay" onClick={() => setShowMoreEvents(null)}>
          <div className="modal-content max-w-lg" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                {showMoreEvents.length} Sessions on {moment(showMoreEvents[0].start).format('MMMM D, YYYY')}
              </h2>
              <button
                onClick={() => setShowMoreEvents(null)}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
              >
                <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {showMoreEvents.map((event) => {
                const session = event.resource;
                const coach = coaches.find((c) => c.id === session.coach_id);
                return (
                  <div
                    key={event.id}
                    onClick={() => {
                      setShowMoreEvents(null);
                      handleSelectEvent(event);
                    }}
                    className="p-4 border border-gray-200 dark:border-gray-700 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer transition-all duration-200"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-gray-900 dark:text-white">{coach?.name || 'Unknown'}</span>
                      <StatusBadge status={session.status} />
                    </div>
                    <div className="flex items-center gap-4 text-sm text-gray-600 dark:text-gray-400">
                      <div className="flex items-center gap-1">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        {session.start_time} - {session.end_time}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-400 mt-1">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                      </svg>
                      <span className="truncate">{session.address}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Session Details Modal */}
      {showModal && selectedSession && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content max-w-lg" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-6">
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Session Details</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">View and manage this session</p>
              </div>
              <StatusBadge status={selectedSession.status} />
            </div>

            <div className="space-y-4 mb-6">
              <div className="flex items-start gap-4 p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                <div className="w-10 h-10 bg-blue-100 dark:bg-blue-900/50 rounded-lg flex items-center justify-center flex-shrink-0">
                  <svg className="w-5 h-5 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                </div>
                <div>
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400 block">Coach</span>
                  <p className="text-gray-900 dark:text-white font-medium">{coaches.find((c) => c.id === selectedSession.coach_id)?.name}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center gap-2 mb-1">
                    <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Date</span>
                  </div>
                  <p className="text-gray-900 dark:text-white font-medium">{moment(selectedSession.date).format('MMM D, YYYY')}</p>
                </div>

                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center gap-2 mb-1">
                    <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Time</span>
                  </div>
                  <p className="text-gray-900 dark:text-white font-medium">{selectedSession.start_time} - {selectedSession.end_time}</p>
                </div>
              </div>

              <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                <div className="flex items-center gap-2 mb-1">
                  <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Location</span>
                </div>
                <p className="text-gray-900 dark:text-white">{selectedSession.address}</p>
              </div>

              {selectedSession.check_in_time && (
                <div className="p-4 bg-green-50 dark:bg-green-900/20 rounded-xl border border-green-200 dark:border-green-800">
                  <div className="flex items-center gap-2 mb-1">
                    <svg className="w-4 h-4 text-green-600 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span className="text-xs font-medium text-green-600 dark:text-green-400">Checked In</span>
                  </div>
                  <p className="text-green-700 dark:text-green-300 font-medium">
                    {new Date(selectedSession.check_in_time._seconds * 1000).toLocaleString()}
                  </p>
                </div>
              )}

              {selectedSession.location_verified !== undefined && (
                <div className={`p-4 rounded-xl border ${
                  selectedSession.location_verified
                    ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
                    : 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800'
                }`}>
                  <div className="flex items-center gap-2">
                    <svg className={`w-4 h-4 ${
                      selectedSession.location_verified
                        ? 'text-green-600 dark:text-green-400'
                        : 'text-yellow-600 dark:text-yellow-400'
                    }`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span className={`text-sm font-medium ${
                      selectedSession.location_verified
                        ? 'text-green-700 dark:text-green-300'
                        : 'text-yellow-700 dark:text-yellow-300'
                    }`}>
                      Location {selectedSession.location_verified ? 'Verified' : 'Not Verified (out of range)'}
                    </span>
                  </div>
                </div>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              {selectedSession.status === 'scheduled' && (
                <button
                  onClick={handleSendReminder}
                  disabled={actionLoading}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {actionLoading ? (
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                  ) : (
                    <>
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                      </svg>
                      Send Reminder
                    </>
                  )}
                </button>
              )}
              <button
                onClick={() => openEditModal(selectedSession)}
                className="btn-secondary flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
                Edit
              </button>
              <button
                onClick={() => handleDeleteSession(selectedSession)}
                className="btn-danger flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                Delete
              </button>
              <button
                onClick={() => setShowModal(false)}
                className="btn-secondary"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Session Modal */}
      {showCreateModal && (
        <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="modal-content max-w-lg max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-xl flex items-center justify-center">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Create Session</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Schedule a new coaching session</p>
              </div>
            </div>

            <form onSubmit={handleCreateSession} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Coach</label>
                <select
                  value={newSession.coach_id}
                  onChange={(e) => setNewSession({ ...newSession, coach_id: e.target.value })}
                  required
                  className="select-field"
                >
                  <option value="">Select a coach</option>
                  {coaches.map((coach) => (
                    <option key={coach.id} value={coach.id}>
                      {coach.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Date</label>
                <input
                  type="date"
                  value={newSession.date}
                  onChange={(e) => setNewSession({ ...newSession, date: e.target.value })}
                  required
                  className="input-field"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Start Time</label>
                  <input
                    type="time"
                    value={newSession.start_time}
                    onChange={(e) => setNewSession({ ...newSession, start_time: e.target.value })}
                    required
                    className="input-field"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">End Time</label>
                  <input
                    type="time"
                    value={newSession.end_time}
                    onChange={(e) => setNewSession({ ...newSession, end_time: e.target.value })}
                    required
                    className="input-field"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Location
                </label>
                <LocationAutocomplete
                  onPlaceSelected={(locationData) => {
                    setNewSession({
                      ...newSession,
                      address: locationData.address,
                      latitude: locationData.latitude.toString(),
                      longitude: locationData.longitude.toString(),
                    });
                  }}
                  defaultValue={newSession.address}
                />
                {newSession.address && (
                  <div className="mt-2 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl">
                    <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-300">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      Location selected: {newSession.address}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {actionLoading ? (
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                  ) : (
                    'Create Session'
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Session Modal */}
      {showEditModal && editSession && (
        <div className="modal-overlay" onClick={() => { setShowEditModal(false); setEditSession(null); }}>
          <div className="modal-content max-w-lg max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-xl flex items-center justify-center">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Edit Session</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Update session details</p>
              </div>
            </div>

            <form onSubmit={handleEditSession} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Coach</label>
                <select
                  value={editSession.coach_id}
                  onChange={(e) => setEditSession({ ...editSession, coach_id: e.target.value })}
                  required
                  className="select-field"
                >
                  <option value="">Select a coach</option>
                  {coaches.map((coach) => (
                    <option key={coach.id} value={coach.id}>
                      {coach.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Date</label>
                <input
                  type="date"
                  value={editSession.date}
                  onChange={(e) => setEditSession({ ...editSession, date: e.target.value })}
                  required
                  className="input-field"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Start Time</label>
                  <input
                    type="time"
                    value={editSession.start_time}
                    onChange={(e) => setEditSession({ ...editSession, start_time: e.target.value })}
                    required
                    className="input-field"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">End Time</label>
                  <input
                    type="time"
                    value={editSession.end_time}
                    onChange={(e) => setEditSession({ ...editSession, end_time: e.target.value })}
                    required
                    className="input-field"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Location
                </label>
                <LocationAutocomplete
                  onPlaceSelected={(locationData) => {
                    setEditSession({
                      ...editSession,
                      address: locationData.address,
                      latitude: locationData.latitude.toString(),
                      longitude: locationData.longitude.toString(),
                    });
                  }}
                  defaultValue={editSession.address}
                />
                {editSession.address && (
                  <div className="mt-2 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl">
                    <div className="flex items-center gap-2 text-sm text-green-700 dark:text-green-300">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      Location: {editSession.address}
                    </div>
                  </div>
                )}
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {actionLoading ? (
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                  ) : (
                    'Update Session'
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => { setShowEditModal(false); setEditSession(null); }}
                  className="btn-secondary"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default Dashboard;
