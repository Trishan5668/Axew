import {
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
  type User as FirebaseUser,
} from 'firebase/auth'
import { firebaseAuth } from '../firebase/firebase'
import type { Profile } from './database.types'

export type FirebaseSession = {
  access_token: string
  expires_at: number | null
}

function getFirebaseAuth(): NonNullable<typeof firebaseAuth> {
  if (!firebaseAuth) {
    throw new Error('Firebase Authentication is not configured for this build.')
  }
  return firebaseAuth
}

export async function signInWithEmail(email: string, password: string): Promise<FirebaseUser> {
  const auth = getFirebaseAuth()
  const cred = await signInWithEmailAndPassword(auth, email, password)
  return cred.user
}

export async function signUpWithEmail(email: string, password: string): Promise<FirebaseUser> {
  const auth = getFirebaseAuth()
  const cred = await createUserWithEmailAndPassword(auth, email, password)
  await sendEmailVerification(cred.user)
  return cred.user
}

export async function signInWithGoogle(): Promise<void> {
  const auth = getFirebaseAuth()
  const provider = new GoogleAuthProvider()
  await signInWithPopup(auth, provider)
}

export async function triggerPasswordReset(email: string): Promise<void> {
  const auth = getFirebaseAuth()
  await sendPasswordResetEmail(auth, email)
}

export async function signOut(): Promise<void> {
  const auth = getFirebaseAuth()
  await firebaseSignOut(auth)
}

export async function getCurrentUser(): Promise<FirebaseUser | null> {
  const auth = getFirebaseAuth()
  return auth.currentUser
}

export async function getCurrentSession(): Promise<FirebaseSession | null> {
  const auth = getFirebaseAuth()
  const user = auth.currentUser
  if (!user) return null
  const token = await user.getIdToken(true)
  return {
    access_token: token,
    expires_at: Date.now() + 60 * 60 * 1000,
  }
}

export async function refreshSession(): Promise<FirebaseSession | null> {
  const auth = getFirebaseAuth()
  const user = auth.currentUser
  if (!user) return null
  const token = await user.getIdToken(true)
  return {
    access_token: token,
    expires_at: Date.now() + 60 * 60 * 1000,
  }
}

export async function getUserProfile(userId: string): Promise<Profile> {
  const auth = getFirebaseAuth()
  const user = auth.currentUser
  if (!user || user.uid !== userId) {
    return {
      id: userId,
      email: '',
      display_name: null,
      avatar_url: null,
      credit_balance: 0,
      total_minutes_processed: 0,
    } as Profile
  }

  return {
    id: user.uid,
    email: user.email ?? '',
    display_name: user.displayName ?? user.email?.split('@')[0] ?? null,
    avatar_url: user.photoURL ?? null,
    credit_balance: 0,
    total_minutes_processed: 0,
  } as Profile
}

export async function updateProfile(
  userId: string,
  updates: Partial<Pick<Profile, 'display_name' | 'avatar_url'>>,
): Promise<Profile> {
  const current = await getUserProfile(userId)
  return {
    ...current,
    ...updates,
  } as Profile
}
