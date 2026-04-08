import { create } from "zustand";

interface Thread {
  id: string;
  title: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

interface ChatStore {
  threads: Thread[];
  activeThreadId: string | null;
  setThreads: (threads: Thread[]) => void;
  setActiveThread: (id: string | null) => void;
  addThread: (thread: Thread) => void;
}

export const useChatStore = create<ChatStore>((set) => ({
  threads: [],
  activeThreadId: null,
  setThreads: (threads) => set({ threads }),
  setActiveThread: (id) => set({ activeThreadId: id }),
  addThread: (thread) =>
    set((state) => ({ threads: [thread, ...state.threads] })),
}));
