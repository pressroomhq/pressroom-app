-- Supabase Auth Migration
-- Run this in the Supabase SQL Editor BEFORE deploying the new app code.
--
-- What this does:
--   1. Creates a `profiles` table linked to auth.users (UUID PK)
--   2. Auto-creates profile on signup via trigger
--   3. Recreates `user_orgs` with UUID user_id (FK to profiles)
--   4. Fixes RLS functions (can_access_org, is_admin) to use profiles/user_orgs
--   5. Sets up RLS on profiles and user_orgs
--   6. Drops old custom auth tables (user_sessions, invite_tokens)

-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. PROFILES TABLE
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  name TEXT DEFAULT '',
  is_admin BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 2. AUTO-CREATE PROFILE ON SIGNUP
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, email, name)
  VALUES (NEW.id, NEW.email, COALESCE(NEW.raw_user_meta_data->>'name', ''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_new_user();

-- ═══════════════════════════════════════════════════════════════════════════════
-- 3. RECREATE user_orgs WITH UUID user_id
-- ═══════════════════════════════════════════════════════════════════════════════

DROP TABLE IF EXISTS user_orgs CASCADE;
CREATE TABLE user_orgs (
  id SERIAL PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, org_id)
);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 4. FIX RLS FUNCTIONS
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION can_access_org(p_org_id INTEGER)
RETURNS BOOLEAN AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM user_orgs
    WHERE user_id = auth.uid() AND org_id = p_org_id
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION is_admin()
RETURNS BOOLEAN AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM profiles
    WHERE id = auth.uid() AND is_admin = TRUE
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 5. RLS ON profiles AND user_orgs
-- ═══════════════════════════════════════════════════════════════════════════════

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if re-running
DROP POLICY IF EXISTS "Users can view own profile" ON profiles;
DROP POLICY IF EXISTS "Users can update own profile" ON profiles;
DROP POLICY IF EXISTS "Service role full access on profiles" ON profiles;

CREATE POLICY "Users can view own profile" ON profiles
  FOR SELECT USING (id = auth.uid());
CREATE POLICY "Users can update own profile" ON profiles
  FOR UPDATE USING (id = auth.uid());
CREATE POLICY "Service role full access on profiles" ON profiles
  FOR ALL USING (auth.role() = 'service_role');

ALTER TABLE user_orgs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own org memberships" ON user_orgs;
DROP POLICY IF EXISTS "Service role full access on user_orgs" ON user_orgs;

CREATE POLICY "Users can view own org memberships" ON user_orgs
  FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "Service role full access on user_orgs" ON user_orgs
  FOR ALL USING (auth.role() = 'service_role');

-- ═══════════════════════════════════════════════════════════════════════════════
-- 6. DROP OLD CUSTOM AUTH TABLES
-- ═══════════════════════════════════════════════════════════════════════════════

DROP TABLE IF EXISTS user_sessions CASCADE;
DROP TABLE IF EXISTS invite_tokens CASCADE;
-- Keep access_requests for now (waitlist)
-- Keep users table as backup — can drop later
