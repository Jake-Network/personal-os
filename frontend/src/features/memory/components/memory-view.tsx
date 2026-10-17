'use client';

import { PageContainer, PageHeader } from '@/components/page-container';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { DecisionJournal } from './decision-journal';
import { MemoryList } from './memory-list';

export function MemoryView() {
  return (
    <PageContainer className='max-w-[900px]'>
      <Tabs defaultValue='memory'>
        <PageHeader
          title='기억 · 의사결정'
          description='확인된 기억만 AI 상담의 개인 프로필로 사용됩니다. 의사결정은 나중에 실제 결과와 비교할 수 있습니다.'
          actions={
            <TabsList>
              <TabsTrigger value='memory'>장기 기억</TabsTrigger>
              <TabsTrigger value='journal'>Decision Journal</TabsTrigger>
            </TabsList>
          }
        />
        <TabsContent value='memory' className='mt-0'>
          <MemoryList />
        </TabsContent>
        <TabsContent value='journal' className='mt-0'>
          <DecisionJournal />
        </TabsContent>
      </Tabs>
    </PageContainer>
  );
}
