import { firebaseAuth } from './firebase';
import {
  GoogleAuthProvider,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  sendPasswordResetEmail,
  sendEmailVerification,
  signOut as firebaseSignOut,
  User,
  IdTokenResult,
} from 'firebase/auth';

/** Firebase Authentication helper functions that mirror the previous Supabase API */

export async function signInWithGoogle(): Promise<void> {
  const provider = new GoogleAuthProvider();
  await signInWithPopup(firebaseAuth!, provider);
}

export async function signInWithEmail(email: string, password: string): Promise<User> {
  const cred = await signInWithEmailAndPassword(firebaseAuth!, email, password);
  return cred.user;
}

export async function signUpWithEmail(email: string, password: string): Promise<User> {
  const cred = await createUserWithEmailAndPassword(firebaseAuth!, email, password);
  // Send verification email after sign‑up.
  await sendEmailVerification(cred.user);
  return cred.user;
}

export async function triggerPasswordReset(email: string): Promise<void> {
  await sendPasswordResetEmail(firebaseAuth!, email);
}

export async function signOut(): Promise<void> {
  await firebaseSignOut(firebaseAuth!);
}

export async function getCurrentUser(): Promise<User | null> {
  return firebaseAuth!.currentUser;
}

/** Retrieve a fresh ID token for the currently signed‑in user. */
export async function getIdToken(forceRefresh = true): Promise<string | null> {
  const user = firebaseAuth!.currentUser;
  if (!user) return null;
  const result: IdTokenResult = await user.getIdTokenResult(forceRefresh);
  return result.token;
}
