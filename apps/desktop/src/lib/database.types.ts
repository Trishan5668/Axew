/**
 * Hand-written Supabase database types matching supabase/migrations/0002-0004.
 *
 * In a CI pipeline these should be regenerated via:
 *   supabase gen types typescript --linked > apps/desktop/src/lib/database.types.ts
 *
 * Until that pipeline exists, this file is the source of truth.
 */

export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[]

export interface Database {
  public: {
    Tables: {
      profiles: {
        Row: {
          id: string
          email: string
          display_name: string | null
          avatar_url: string | null
          created_at: string
          updated_at: string
          total_minutes_processed: number
          credit_balance: number
        }
        Insert: {
          id: string
          email: string
          display_name?: string | null
          avatar_url?: string | null
          total_minutes_processed?: number
          credit_balance?: number
        }
        Update: {
          email?: string
          display_name?: string | null
          avatar_url?: string | null
          total_minutes_processed?: number
          credit_balance?: number
        }
        Relationships: []
      }
      payments: {
        Row: {
          id: string
          user_id: string
          razorpay_order_id: string
          razorpay_payment_id: string | null
          razorpay_signature: string | null
          plan_id: 'starter' | 'creator' | 'pro'
          amount_inr: number
          credits_purchased: number
          status: 'created' | 'paid' | 'failed' | 'refunded'
          created_at: string
          paid_at: string | null
          failure_reason: string | null
        }
        Insert: {
          user_id: string
          razorpay_order_id: string
          plan_id: 'starter' | 'creator' | 'pro'
          amount_inr: number
          credits_purchased: number
          status?: 'created' | 'paid' | 'failed' | 'refunded'
        }
        Update: {
          razorpay_payment_id?: string | null
          razorpay_signature?: string | null
          status?: 'created' | 'paid' | 'failed' | 'refunded'
          paid_at?: string | null
          failure_reason?: string | null
        }
        Relationships: [{
          foreignKeyName: 'payments_user_id_fkey'
          columns: ['user_id']
          referencedRelation: 'profiles'
          referencedColumns: ['id']
        }]
      }
    }
    Views: Record<string, never>
    Functions: {
      apply_payment_credits: {
        Args: {
          p_payment_id: string
          p_razorpay_payment_id: string
          p_razorpay_signature: string
        }
        Returns: boolean
      }
      deduct_credits: {
        Args: { p_user_id: string; p_minutes: number }
        Returns: number
      }
      get_credit_summary: {
        Args: { p_user_id: string }
        Returns: {
          credit_balance: number
          total_minutes_processed: number
          free_tier_minutes: number
        }[]
      }
    }
    Enums: Record<string, never>
    CompositeTypes: Record<string, never>
  }
}

export type Profile = Database['public']['Tables']['profiles']['Row']
export type Payment = Database['public']['Tables']['payments']['Row']
export type PlanId = Database['public']['Tables']['payments']['Row']['plan_id']
