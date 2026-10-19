'use client';

import { Suspense } from 'react';

import { Section } from '@/components/page-container';
import { ListSkeleton } from '@/components/skeleton';

import { GoogleConnectionControls } from './google-connection';
import { LegacySheetsImport, MarketConnection } from './market-connection';

/** Optional automatic quotes. Personal finance records stay local whether or not this is connected. */
export function MarketSettings() {
  return (
    <>
      <p className='mb-5 text-muted-foreground'>자동 시세는 선택 사항입니다. 연결하지 않아도 자산을 기록하고 직접 입력한 가격으로 평가할 수 있습니다.</p>
      <Section
        title='Google 계정'
        info={
          <>
            <p>앱이 만든 시세 전용 파일에 대한 권한과 계정 확인 권한만 요청합니다.</p>
            <p>Google 연결은 앱 잠금이나 AI 연결과 별개이며, 다른 계정으로 자동 전환하지 않습니다.</p>
          </>
        }>
        {/* The sign-in returns with ?google_oauth=…, read through useSearchParams. */}
        <Suspense fallback={<ListSkeleton rows={2} />}>
          <GoogleConnectionControls />
        </Suspense>
      </Section>
      <Section
        title='시세 파일'
        info={
          <>
            <p>새 전용 파일에 종목 코드와 통화쌍, 시세 수식만 저장합니다. 계좌·수량·원가·메모는 보내지 않습니다.</p>
            <p>Google에는 조회한 종목 코드가 남고, 무료 시세는 늦거나 지원되지 않을 수 있습니다. 갱신은 5분에 한 번으로 제한됩니다.</p>
            <p>새 파일로 연결해도 기존 Google 파일과 로컬 기록은 그대로 남습니다.</p>
          </>
        }>
        <MarketConnection />
      </Section>
      <Section
        title='예전 Sheets 자료 옮기기'
        info={
          <>
            <p>이전 버전에서 보존해 둔 가져오기 번호로 보유 종목을 로컬 기록으로 옮깁니다. 원격 파일은 바꾸지 않습니다.</p>
            <p>같은 종목이라도 다른 계좌의 행은 합치지 않습니다. 예전 시트의 개인정보는 자동으로 지워지지 않으니 Google에서 직접 확인하세요.</p>
          </>
        }>
        <LegacySheetsImport />
      </Section>
    </>
  );
}
