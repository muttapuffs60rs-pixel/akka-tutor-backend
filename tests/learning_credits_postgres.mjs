// Run after installing @electric-sql/pglite, or set PGLITE_MODULE to a module URL.
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
import fs from 'node:fs';
import assert from 'node:assert/strict';
const db = new PGlite();
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
CREATE SCHEMA auth;
CREATE TABLE auth.users(id uuid PRIMARY KEY,created_at timestamptz DEFAULT now());
CREATE TABLE public.profiles(id uuid PRIMARY KEY,subscription_tier text,subscription_start_date timestamptz,subscription_expires_at timestamptz,chats_today int DEFAULT 0);
CREATE TABLE public.chat_sessions(id uuid PRIMARY KEY,user_id uuid);
CREATE TABLE public.ai_chat_requests(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),user_id uuid,session_id uuid,
 created_at timestamptz DEFAULT now(), status text DEFAULT 'reserved', execution_id uuid, input_tokens bigint,output_tokens bigint,
 vision_input_tokens bigint,vision_output_tokens bigint,response_source text,answer_cache_id uuid,
 response_text text,response_expires_at timestamptz);
CREATE FUNCTION public.reset_daily_usage(target_user_id uuid) RETURNS jsonb LANGUAGE sql AS
 'SELECT to_jsonb(p) FROM public.profiles p WHERE id=target_user_id';`);
await db.exec(fs.readFileSync(new URL('../supabase_learning_credits.sql', import.meta.url),'utf8'));
const query = async (sql,args=[]) => (await db.query(sql,args)).rows;
const scalar = async(sql,args=[]) => (await query(sql,args))[0].result;
const user = async (fresh=true,tier='free') => {
 const [{id}] = await query(`INSERT INTO auth.users(id,created_at) VALUES(gen_random_uuid(),now() ${fresh ? '' : "- interval '1 day'"}) RETURNING id`);
 await query('INSERT INTO profiles(id,subscription_tier) VALUES($1,$2)',[id,tier]);return id;
};
const request = async u => (await query("INSERT INTO ai_chat_requests(user_id,status,execution_id) VALUES($1,'processing',gen_random_uuid()) RETURNING id,execution_id",[u]))[0];
const balance = u => scalar('SELECT learning_credit_balance($1) result',[u]);
const begin = (u,r) => scalar('SELECT begin_learning_credit_request($1,$2) result',[u,r.id]);
const finish = (u,r,status='cached',input=0,output=0) => scalar('SELECT finish_learning_credit_request($1,$2,$3,$4::jsonb) result',
 [u,r.id,r.execution_id,JSON.stringify({status,input_tokens:input,output_tokens:output,response_source:status==='cached'?'cache':'ai',response_text:'answer'})]);
let checks=0; const ok=(a,b)=>{assert.deepEqual(a,b);checks++;};
const old=await user(false);ok((await balance(old)).welcome_remaining,0);
const oldDenied=await request(old);ok((await begin(old,oldDenied)).error,'credit_limit');
ok((await balance(old)).daily_remaining,0);
const fresh=await user();ok((await balance(fresh)).welcome_remaining,50000);
const r=await request(fresh);ok((await begin(fresh,r)).enabled,true);
const competing=await request(fresh);ok((await begin(fresh,competing)).error,'credit_busy');
await finish(fresh,competing,'failed');ok((await balance(fresh)).active,true);
ok((await finish(fresh,r,'complete',19000,1000)).charged,20000);
ok((await balance(fresh)).daily_remaining,0);ok((await balance(fresh)).welcome_remaining,30000);
const failed=await request(fresh);await begin(fresh,failed);await finish(fresh,failed,'failed',100,20);
ok((await balance(fresh)).welcome_remaining,30000);
await query("UPDATE learning_credit_wallets SET credit_date=credit_date-1,daily_remaining=3000 WHERE user_id=$1",[fresh]);
ok((await balance(fresh)).daily_remaining,0);ok((await balance(fresh)).welcome_remaining,30000);
await query('UPDATE learning_credit_wallets SET daily_remaining=0,welcome_remaining=100 WHERE user_id=$1',[old]);
const over=await request(old);await begin(old,over);await finish(old,over,'complete',150,50);
ok((await balance(old)).completion_overrun,100);
const denied=await request(old);ok((await begin(old,denied)).error,'credit_limit');
await query('UPDATE learning_credit_wallets SET credit_date=credit_date-1 WHERE user_id=$1',[old]);
ok((await balance(old)).daily_remaining,0);ok((await balance(old)).completion_overrun,100);
const paid=await user(true,'tier_999');const pr=await request(paid);ok((await begin(paid,pr)).enabled,false);ok((await finish(paid,pr)).charged,3000);
const mid=await request(fresh);await begin(fresh,mid);
await query('UPDATE learning_credit_wallets SET credit_date=credit_date-1,daily_remaining=5000 WHERE user_id=$1',[fresh]);
ok((await balance(fresh)).daily_remaining,5000);await finish(fresh,mid);
ok((await balance(fresh)).daily_remaining,0);
const [{count}] = await query("SELECT count(*)::int count FROM ai_chat_requests WHERE response_source='cache' AND input_tokens=0 AND learning_credits_charged=3000");ok(count,2);

// Top-ups: idempotent grants, no tier replacement, existing balances first, expiry.
const topUser=await user(false);
const grant=(u,p,o)=>scalar('SELECT grant_learning_credit_topup($1,$2,$3) result',[u,p,o]);
const pack=await grant(topUser,'pay_test','order_test');
ok(pack.remaining,300000);ok((await grant(topUser,'pay_test','order_test')).expires_at,pack.expires_at);
const tr=await request(topUser);await begin(topUser,tr);await finish(topUser,tr);
ok((await balance(topUser)).topup_remaining,297000);
await query('UPDATE learning_credit_wallets SET daily_remaining=0,welcome_remaining=0 WHERE user_id=$1',[topUser]);
const tr2=await request(topUser);ok((await begin(topUser,tr2)).remaining,297000);await finish(topUser,tr2);
ok((await balance(topUser)).topup_remaining,294000);await finish(topUser,tr2);ok((await balance(topUser)).topup_remaining,294000);
await query("UPDATE learning_credit_topups SET expires_at=now()-interval '1 second' WHERE user_id=$1",[topUser]);
ok((await balance(topUser)).topup_remaining,0);
const blocked=await request(topUser);ok((await begin(topUser,blocked)).error,'credit_limit');
const paidPack=await user(true,'tier_199');await grant(paidPack,'pay_paid','order_paid');
await query("INSERT INTO ai_chat_requests(user_id,status,learning_credits_charged) VALUES($1,'complete',3000000)",[paidPack]);
const pp=await request(paidPack);await begin(paidPack,pp);await finish(paidPack,pp);
ok((await balance(paidPack)).topup_remaining,297000);
ok((await query('SELECT subscription_tier FROM profiles WHERE id=$1',[paidPack]))[0].subscription_tier,'tier_199');

const soloExpiry=await query("SELECT abs(extract(epoch FROM (expires_at-granted_at-interval '10 days'))) < 1 AS correct FROM learning_credit_topups WHERE payment_id='pay_test'");
// pay_test was intentionally expired above; use a fresh standalone purchase.
await grant(topUser,'pay_solo_new','order_solo_new');
ok((await query("SELECT abs(extract(epoch FROM (expires_at-granted_at-interval '10 days'))) < 1 AS correct FROM learning_credit_topups WHERE payment_id='pay_solo_new'"))[0].correct,true);
const activeUser=await user(true,'tier_499');
await query("UPDATE profiles SET subscription_start_date=now()-interval '23 days',subscription_expires_at=now()+interval '7 days' WHERE id=$1",[activeUser]);
const aligned=await grant(activeUser,'pay_active','order_active');
ok((await query("SELECT p.subscription_expires_at=t.expires_at AS correct FROM profiles p JOIN learning_credit_topups t ON t.user_id=p.id WHERE t.payment_id='pay_active'"))[0].correct,true);
await query("UPDATE profiles SET subscription_expires_at=now()+interval '30 days' WHERE id=$1",[activeUser]);
ok((await grant(activeUser,'pay_active','order_active')).expires_at,aligned.expires_at);
await query("UPDATE profiles SET subscription_expires_at=now()-interval '1 day' WHERE id=$1",[activeUser]);
await grant(activeUser,'pay_expired','order_expired');
ok((await query("SELECT abs(extract(epoch FROM (expires_at-granted_at-interval '10 days'))) < 1 AS correct FROM learning_credit_topups WHERE payment_id='pay_expired'"))[0].correct,true);
// Apply the incremental migration repeatedly to legacy balances. Never regrant.
const migrated=await user();await balance(migrated);
await query("UPDATE learning_credit_wallets SET welcome_remaining=12345,daily_remaining=15000,credit_date=credit_date-1 WHERE user_id=$1",[migrated]);
const eligibilityBefore=await query('SELECT welcome_from FROM learning_credit_policy');
for(let i=0;i<2;i++) await db.exec(fs.readFileSync(new URL('../supabase_welcome_only_credits.sql', import.meta.url),'utf8'));
const migratedBalance=await balance(migrated);
ok(migratedBalance.daily_remaining,0);ok(migratedBalance.daily_allowance,0);
ok(migratedBalance.welcome_remaining,12345);ok(migratedBalance.remaining,12345);
ok(migratedBalance.welcome_allowance,50000);ok(migratedBalance.resets_at,null);
ok(await query('SELECT welcome_from FROM learning_credit_policy'),eligibilityBefore);
const mr=await request(migrated);await begin(migrated,mr);await finish(migrated,mr);
ok((await balance(migrated)).welcome_remaining,9345);
ok((await finish(migrated,mr)).replayed,true);ok((await balance(migrated)).welcome_remaining,9345);
await query("UPDATE learning_credit_wallets SET credit_date=credit_date-30 WHERE user_id=$1",[migrated]);
ok((await balance(migrated)).remaining,9345);
// A genuinely new eligible account still receives the grant exactly once.
const newAfter=await user();ok((await balance(newAfter)).remaining,50000);ok((await balance(newAfter)).remaining,50000);
await db.close();console.log(`PASS: ${checks} PostgreSQL assertions (isolated database; no production writes).`);
